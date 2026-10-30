"""Voice providers follow LLM_PROVIDER unless set, so a real server never
silently uses the mock (which returns one fixed sentence for every recording)."""

import pytest
from app.core.config import settings
from app.integrations import stt, tts
from app.integrations.stt.live import GeminiLiveTranscriber, get_live_transcriber


def test_blank_voice_providers_follow_the_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "k")
    monkeypatch.setattr(settings, "stt_provider", "")
    monkeypatch.setattr(settings, "tts_provider", "")

    assert stt.get_provider().name == "gemini"
    assert tts.get_provider().name == "gemini"
    assert isinstance(get_live_transcriber(), GeminiLiveTranscriber)


def test_explicit_mock_still_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "stt_provider", "mock")
    monkeypatch.setattr(settings, "tts_provider", "mock")

    assert stt.get_provider().name == "mock"
    assert tts.get_provider().name == "mock"
