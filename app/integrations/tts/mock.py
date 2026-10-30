"""Offline text-to-speech for tests and keyless dev: a short silent WAV."""

from app.integrations.tts.base import TTSProvider, TTSResult
from app.integrations.tts.wav import pcm_to_wav

# Records what was asked for, so tests can check the spoken text.
calls: list[dict[str, str]] = []


def clear() -> None:
    calls.clear()


class MockTTSProvider(TTSProvider):
    name = "mock"

    async def synthesize(self, text: str, *, language: str) -> TTSResult:
        calls.append({"text": text, "language": language})
        silence = b"\x00\x00" * 2400  # 0.1 s at 24 kHz
        return TTSResult(audio=pcm_to_wav(silence, 24000), mime_type="audio/wav", model="mock")
