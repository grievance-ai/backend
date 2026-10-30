"""Voice messages: transcription, the signed transcript token, and audit fields."""

import secrets
import uuid
from typing import Any

import jwt
import pytest
from app.core.config import settings
from app.integrations.llm import mock as llm_mock
from app.integrations.stt import mock as stt_mock
from app.integrations.stt.base import STTError
from app.models.conversation import ConversationMessage
from app.services.voice_service import signing_key
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

NS = "/api/v2/xuanwu"
TRANSCRIBE = f"{NS}/resource/conversations/transcriptions"
SEND = f"{NS}/resource/conversations/messages"
AUDIO = b"\x1aE\xdf\xa3" + b"\x00" * 4000  # long enough to pass the size floor


async def _citizen(client: AsyncClient) -> str:
    mobile = "9" + "".join(secrets.choice("0123456789") for _ in range(9))
    resp = await client.post(
        f"{NS}/identity/sessions/mobile", json={"mobile": mobile, "otp": "1111"}
    )
    assert resp.status_code == 200, resp.text
    return str(resp.json()["data"]["csrf_token"])


def _reply() -> dict[str, Any]:
    return {
        "mode": "grievance",
        "answer_status": "answered",
        "reply": "Sorry to hear that. Since when?",
        "schemes": [],
        "follow_ups": [],
        "facts": [],
    }


async def _transcribe(
    client: AsyncClient,
    csrf: str,
    *,
    audio: bytes = AUDIO,
    mime: str = "audio/webm;codecs=opus",
    language: str = "en",
) -> Any:
    return await client.post(
        TRANSCRIBE,
        files={"audio": ("clip.webm", audio, mime)},
        data={"language": language, "duration_ms": "4200"},
        headers={"X-CSRF-Token": csrf},
    )


async def test_requires_login(client: AsyncClient) -> None:
    resp = await client.post(TRANSCRIBE, files={"audio": ("a.webm", AUDIO, "audio/webm")})
    assert resp.status_code == 401


async def test_corrected_voice_message_keeps_both_transcripts(
    client: AsyncClient, db: AsyncSession
) -> None:
    csrf = await _citizen(client)
    stt_mock.queue_transcript("No water in Rampur for a weak.")

    resp = await _transcribe(client, csrf)

    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["text"] == "No water in Rampur for a weak."
    token = data["voice_token"]

    llm_mock.queue_response(_reply())
    sent = await client.post(
        SEND,
        json={"text": "No water in Rampur for a week.", "language": "en", "voice_token": token},
        headers={"X-CSRF-Token": csrf},
    )

    assert sent.status_code == 200, sent.text
    user_message = sent.json()["data"]["user_message"]
    assert user_message["source"] == "voice"
    assert user_message["content"] == "No water in Rampur for a week."
    row = await db.get(ConversationMessage, uuid.UUID(user_message["id"]))
    assert row is not None
    assert row.source == "voice"
    assert row.original_transcript == "No water in Rampur for a weak."
    assert row.transcript_corrected is True
    assert row.audio_duration_ms == 4200
    assert row.audio_storage_key is not None and row.audio_storage_key.endswith(".webm")


async def test_unedited_transcript_is_not_marked_corrected(
    client: AsyncClient, db: AsyncSession
) -> None:
    csrf = await _citizen(client)
    data = (await _transcribe(client, csrf, language="pa")).json()["data"]

    llm_mock.queue_response(_reply())
    sent = await client.post(
        SEND,
        json={"text": data["text"], "language": "pa", "voice_token": data["voice_token"]},
        headers={"X-CSRF-Token": csrf},
    )

    assert sent.status_code == 200, sent.text
    row = await db.scalar(
        select(ConversationMessage).where(
            ConversationMessage.id == uuid.UUID(sent.json()["data"]["user_message"]["id"])
        )
    )
    assert row is not None
    assert row.original_transcript == data["text"]
    assert row.transcript_corrected is False


async def test_typed_message_stays_typed(client: AsyncClient) -> None:
    csrf = await _citizen(client)
    llm_mock.queue_response(_reply())
    sent = await client.post(
        SEND, json={"text": "Hello", "language": "en"}, headers={"X-CSRF-Token": csrf}
    )
    assert sent.json()["data"]["user_message"]["source"] == "typed"


@pytest.mark.parametrize(
    ("audio", "mime", "error"),
    [
        (AUDIO, "application/pdf", "resource.voice.unsupported_format"),
        (b"tiny", "audio/webm", "resource.voice.too_short"),
    ],
)
async def test_bad_audio_is_rejected(
    client: AsyncClient, audio: bytes, mime: str, error: str
) -> None:
    csrf = await _citizen(client)
    resp = await _transcribe(client, csrf, audio=audio, mime=mime)
    assert resp.status_code == 422
    assert resp.json()["errors"] == [error]


async def test_oversized_audio_is_rejected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "stt_max_bytes", 2000)
    csrf = await _citizen(client)
    resp = await _transcribe(client, csrf)
    assert resp.status_code == 422
    assert resp.json()["errors"] == ["resource.voice.too_large"]


async def test_silence_returns_no_speech(client: AsyncClient) -> None:
    csrf = await _citizen(client)
    stt_mock.queue_transcript("")
    resp = await _transcribe(client, csrf)
    assert resp.status_code == 422
    assert resp.json()["errors"] == ["resource.voice.no_speech"]


async def test_provider_failure_is_a_clean_error(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise STTError("gemini returned 503")

    monkeypatch.setattr(stt_mock.MockSTTProvider, "transcribe", boom)
    csrf = await _citizen(client)
    resp = await _transcribe(client, csrf)
    assert resp.status_code == 502
    assert resp.json()["errors"] == ["resource.voice.transcription_failed"]


async def test_token_from_another_citizen_is_refused(client: AsyncClient, db: AsyncSession) -> None:
    csrf = await _citizen(client)
    token = (await _transcribe(client, csrf)).json()["data"]["voice_token"]

    other_csrf = await _citizen(client)  # cookies now belong to someone else
    resp = await client.post(
        SEND,
        json={"text": "Hijacked", "language": "en", "voice_token": token},
        headers={"X-CSRF-Token": other_csrf},
    )

    assert resp.status_code == 422
    assert resp.json()["errors"] == ["resource.voice.invalid_token"]
    saved = await db.scalar(
        select(ConversationMessage).where(ConversationMessage.content == "Hijacked")
    )
    assert saved is None


@pytest.mark.parametrize("kind", ["forged", "expired", "garbage"])
async def test_forged_or_expired_token_is_refused(client: AsyncClient, kind: str) -> None:
    csrf = await _citizen(client)
    real = (await _transcribe(client, csrf)).json()["data"]["voice_token"]
    sub = jwt.decode(real, options={"verify_signature": False})["sub"]

    if kind == "forged":
        token = jwt.encode(
            {"aud": "voice-transcript", "sub": sub, "exp": 9_999_999_999, "txt": "fake"},
            b"x" * 32,
            algorithm="HS256",
        )
    elif kind == "expired":
        token = jwt.encode(
            {"aud": "voice-transcript", "sub": sub, "exp": 1, "txt": "old"},
            signing_key(),
            algorithm="HS256",
        )
    else:
        token = "not-a-token"

    resp = await client.post(
        SEND,
        json={"text": "Hello", "language": "en", "voice_token": token},
        headers={"X-CSRF-Token": csrf},
    )
    assert resp.status_code == 422
    assert resp.json()["errors"] == ["resource.voice.invalid_token"]


# --- Spoken replies ----------------------------------------------------------


async def _assistant_reply(client: AsyncClient, csrf: str, reply: str) -> str:
    llm_mock.queue_response({**_reply(), "reply": reply})
    sent = await client.post(
        SEND, json={"text": "Hello", "language": "pa"}, headers={"X-CSRF-Token": csrf}
    )
    assert sent.status_code == 200, sent.text
    return str(sent.json()["data"]["assistant_message"]["id"])


async def test_reply_is_read_aloud(client: AsyncClient) -> None:
    from app.integrations.tts import mock as tts_mock

    csrf = await _citizen(client)
    message_id = await _assistant_reply(
        client, csrf, "**Water** problem noted. See https://example.gov.in for more."
    )

    resp = await client.post(f"{SEND}/{message_id}/speech", headers={"X-CSRF-Token": csrf})

    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "audio/wav"
    assert resp.content.startswith(b"RIFF")
    # Markdown and links are not read out; the reply's language is used.
    assert tts_mock.calls[-1] == {"text": "Water problem noted. See for more.", "language": "pa"}


async def test_cannot_hear_someone_elses_reply(client: AsyncClient) -> None:
    csrf = await _citizen(client)
    message_id = await _assistant_reply(client, csrf, "Private answer.")

    other_csrf = await _citizen(client)
    resp = await client.post(f"{SEND}/{message_id}/speech", headers={"X-CSRF-Token": other_csrf})
    assert resp.status_code == 404


async def test_citizen_messages_are_not_spoken(client: AsyncClient) -> None:
    csrf = await _citizen(client)
    llm_mock.queue_response(_reply())
    sent = await client.post(
        SEND, json={"text": "Hello", "language": "en"}, headers={"X-CSRF-Token": csrf}
    )
    own_id = sent.json()["data"]["user_message"]["id"]
    resp = await client.post(f"{SEND}/{own_id}/speech", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 404


async def test_speech_failure_is_a_clean_error(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.integrations.tts import mock as tts_mock
    from app.integrations.tts.base import TTSError

    async def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise TTSError("gemini returned 429")

    csrf = await _citizen(client)
    message_id = await _assistant_reply(client, csrf, "Hello there.")
    monkeypatch.setattr(tts_mock.MockTTSProvider, "synthesize", boom)
    resp = await client.post(f"{SEND}/{message_id}/speech", headers={"X-CSRF-Token": csrf})
    assert resp.status_code == 502
    assert resp.json()["errors"] == ["resource.voice.speech_failed"]


def test_long_replies_are_cut_at_a_sentence_end() -> None:
    from app.services.voice_service import speakable

    text = "ਪਹਿਲਾ ਵਾਕ ਹੈ। ਦੂਜਾ ਵਾਕ ਬਹੁਤ ਲੰਮਾ ਹੈ ਅਤੇ ਕੱਟਿਆ ਜਾਵੇਗਾ"
    assert speakable(text, 25) == "ਪਹਿਲਾ ਵਾਕ ਹੈ।"
    assert speakable("Short.", 25) == "Short."
