"""Gemini text-to-speech (``generateContent`` with an AUDIO response).

Only the reply text is sent, never an instruction, because the model sometimes
reads instructions aloud. Checked by transcribing the audio back.
Gemini normally returns a complete WAV; raw ``audio/L16`` PCM is wrapped as a fallback.
"""

import base64
import re
from typing import Any

from app.core.config import settings
from app.integrations.llm.base import LLMError
from app.integrations.llm.gemini import call_gemini
from app.integrations.tts.base import TTSError, TTSProvider, TTSResult
from app.integrations.tts.wav import pcm_to_wav


class GeminiTTSProvider(TTSProvider):
    name = "gemini"

    def __init__(self) -> None:
        self.api_key = settings.gemini_api_key
        if not self.api_key:
            raise TTSError("GEMINI_API_KEY is not set")
        self.models = [settings.tts_model]
        if settings.tts_fallback_model and settings.tts_fallback_model != settings.tts_model:
            self.models.append(settings.tts_fallback_model)

    async def synthesize(self, text: str, *, language: str) -> TTSResult:
        body: dict[str, Any] = {
            # Only the reply itself. Any instruction in here ("read this in a warm
            # voice...") can be spoken aloud, so none is sent: the language comes from
            # the script (Gurmukhi is read as Punjabi) and the voice from the config.
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": settings.tts_voice}}
                },
            },
        }
        try:
            payload, model, latency_ms = await call_gemini(
                api_key=self.api_key, models=self.models, body=body
            )
        except LLMError as exc:
            raise TTSError(str(exc)) from exc

        parts = (payload.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        inline = next((p["inlineData"] for p in parts if "inlineData" in p), None)
        if not inline or not inline.get("data"):
            raise TTSError("gemini returned no audio")
        audio = base64.b64decode(inline["data"])
        mime = str(inline.get("mimeType", ""))
        if not audio.startswith(b"RIFF"):
            # Raw PCM, e.g. "audio/L16;codec=pcm;rate=24000".
            rate = re.search(r"rate=(\d+)", mime)
            audio = pcm_to_wav(audio, int(rate.group(1)) if rate else 24000)
        return TTSResult(audio=audio, mime_type="audio/wav", model=model, latency_ms=latency_ms)
