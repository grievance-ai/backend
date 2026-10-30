"""Live voice transcription session (the WebSocket protocol), driven by a fake socket."""

import secrets
import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
import redis.asyncio as redis
from app.core.config import settings
from app.integrations.llm import mock as llm_mock
from app.integrations.stt import live
from app.integrations.stt.base import STTError
from app.models.conversation import ConversationMessage
from app.services import live_voice
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

NS = "/api/v2/xuanwu"
PATH = f"{NS}/resource/conversations/live-transcription"
ORIGIN = "http://localhost:3100"
CHUNK = b"\x01\x00" * 3200  # 200 ms of 16 kHz audio


class FakeSocket:
    def __init__(self, inbox: list[dict[str, Any]], *, cookies: dict[str, str], origin: str):
        self.headers = {"origin": origin}
        self.cookies = cookies
        self.url = SimpleNamespace(path=PATH)
        self.inbox = inbox
        self.sent: list[dict[str, Any]] = []
        self.accepted = False
        self.close_code: int | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def receive(self) -> dict[str, Any]:
        return self.inbox.pop(0) if self.inbox else {"type": "websocket.disconnect"}

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)

    async def close(self, code: int = 1000) -> None:
        self.close_code = code


def audio(n: int) -> list[dict[str, Any]]:
    return [{"type": "websocket.receive", "bytes": CHUNK} for _ in range(n)]


def command(kind: str) -> dict[str, Any]:
    return {"type": "websocket.receive", "text": f'{{"type": "{kind}"}}'}


@pytest_asyncio.fixture
async def test_redis() -> AsyncIterator[redis.Redis]:
    client: redis.Redis = redis.from_url(settings.redis_url)  # type: ignore[no-untyped-call]
    yield client
    await client.aclose()


@pytest.fixture(autouse=True)
def _allow_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "cors_origins", ORIGIN)
    live.clear()


async def _login(client: AsyncClient) -> tuple[str, dict[str, str]]:
    mobile = "9" + "".join(secrets.choice("0123456789") for _ in range(9))
    resp = await client.post(
        f"{NS}/identity/sessions/mobile", json={"mobile": mobile, "otp": "1111"}
    )
    assert resp.status_code == 200, resp.text
    cookies = {settings.access_cookie_name: client.cookies[settings.access_cookie_name]}
    return str(resp.json()["data"]["csrf_token"]), cookies


async def _run(
    socket: FakeSocket, db: AsyncSession, test_redis: redis.Redis, language: str = "en"
) -> list[dict[str, Any]]:
    await live_voice.run(socket, language, db=db, redis_client=test_redis)  # type: ignore[arg-type]
    return socket.sent


async def test_words_stream_and_the_final_text_can_be_sent(
    client: AsyncClient, db: AsyncSession, test_redis: redis.Redis
) -> None:
    csrf, cookies = await _login(client)
    live.queue_live_transcript("Water stopped in Rampur.")
    socket = FakeSocket([*audio(3), command("end")], cookies=cookies, origin=ORIGIN)

    sent = await _run(socket, db, test_redis)

    assert sent[0] == {"type": "ready"}
    assert [m["text"] for m in sent if m["type"] == "partial"] == [
        "Water",
        "Water stopped",
        "Water stopped in",
    ]
    final = sent[-1]
    assert final["type"] == "final" and final["text"] == "Water stopped in Rampur."

    llm_mock.queue_response(
        {
            "mode": "grievance",
            "answer_status": "answered",
            "reply": "Noted.",
            "schemes": [],
            "follow_ups": [],
            "facts": [],
        }
    )
    resp = await client.post(
        f"{NS}/resource/conversations/messages",
        json={"text": final["text"], "language": "en", "voice_token": final["voice_token"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 200, resp.text
    row = await db.get(ConversationMessage, uuid.UUID(resp.json()["data"]["user_message"]["id"]))
    assert row is not None
    assert row.source == "voice"
    assert row.original_transcript == "Water stopped in Rampur."
    assert row.audio_duration_ms == 600
    assert row.audio_storage_key is not None and row.audio_storage_key.endswith(".wav")


@pytest.mark.parametrize(
    ("origin", "with_cookie"), [("https://evil.example", True), (ORIGIN, False)]
)
async def test_other_sites_and_anonymous_users_are_refused(
    client: AsyncClient,
    db: AsyncSession,
    test_redis: redis.Redis,
    origin: str,
    with_cookie: bool,
) -> None:
    _, cookies = await _login(client)
    socket = FakeSocket(
        [*audio(3), command("end")], cookies=cookies if with_cookie else {}, origin=origin
    )
    sent = await _run(socket, db, test_redis)
    assert socket.accepted is False
    assert socket.close_code == 1008
    assert sent == []


async def test_cancel_keeps_nothing(
    client: AsyncClient, db: AsyncSession, test_redis: redis.Redis
) -> None:
    _, cookies = await _login(client)
    socket = FakeSocket([*audio(3), command("cancel")], cookies=cookies, origin=ORIGIN)
    sent = await _run(socket, db, test_redis)
    assert not [m for m in sent if m["type"] in ("final", "error")]


@pytest.mark.parametrize(
    ("transcript", "chunks", "code"), [("Hello there.", 1, "too_short"), ("", 3, "no_speech")]
)
async def test_short_or_silent_recordings_are_errors(
    client: AsyncClient,
    db: AsyncSession,
    test_redis: redis.Redis,
    transcript: str,
    chunks: int,
    code: str,
) -> None:
    _, cookies = await _login(client)
    live.queue_live_transcript(transcript)
    socket = FakeSocket([*audio(chunks), command("end")], cookies=cookies, origin=ORIGIN)
    sent = await _run(socket, db, test_redis)
    assert sent[-1] == {"type": "error", "code": code}


async def test_rate_limit_and_outage_tell_the_client_to_fall_back(
    client: AsyncClient,
    db: AsyncSession,
    test_redis: redis.Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, cookies = await _login(client)

    async def down(_self: Any) -> None:
        raise STTError("live transcription unavailable")

    monkeypatch.setattr(live.MockLiveTranscriber, "open", down)
    sent = await _run(FakeSocket(audio(1), cookies=cookies, origin=ORIGIN), db, test_redis)
    assert sent == [{"type": "error", "code": "unavailable"}]

    monkeypatch.setattr(settings, "stt_live_per_minute", 0)
    sent = await _run(FakeSocket(audio(1), cookies=cookies, origin=ORIGIN), db, test_redis)
    assert sent == [{"type": "error", "code": "rate_limited"}]
