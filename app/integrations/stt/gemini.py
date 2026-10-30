"""Gemini speech-to-text: the audio goes inline to ``generateContent``.

Uses the same key, retry and fallback logic as the assistant
(``app/integrations/llm/gemini.py``). Gemini returns no confidence score.
"""

import base64
from typing import Any

from app.core.config import settings
from app.integrations.llm.base import LLMError
from app.integrations.llm.gemini import call_gemini, model_chain, parse_json_output
from app.integrations.stt.base import STTError, STTProvider, STTResult

_INSTRUCTION = (
    "You transcribe short voice messages from citizens of Punjab, India, to a "
    "government help desk. Write exactly what the speaker says, word for word. "
    "Do not translate, summarise, answer, or add anything. Write Punjabi in Gurmukhi "
    "script, English in Latin script, and keep mixed speech mixed, as spoken. "
    "Hindi stays in Devanagari. Add normal punctuation. Leave out filler sounds "
    "(um, uh) and background noise. If there is no intelligible speech, return an "
    'empty "text". Set "language" to the main language spoken: "pa", "en", "hi" '
    'or "other".'
)

_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "properties": {
        "text": {"type": "STRING"},
        "language": {"type": "STRING", "enum": ["pa", "en", "hi", "other"]},
    },
    "required": ["text", "language"],
}


class GeminiSTTProvider(STTProvider):
    name = "gemini"

    def __init__(self) -> None:
        self.api_key = settings.gemini_api_key
        self.model = settings.stt_model or settings.llm_model
        if not self.api_key:
            raise STTError("GEMINI_API_KEY is not set")

    async def transcribe(self, audio: bytes, *, mime_type: str, language: str) -> STTResult:
        hint = "Punjabi" if language == "pa" else "English"
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": _INSTRUCTION}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": f"The app is set to {hint}. Transcribe this voice message."},
                        {
                            "inlineData": {
                                "mimeType": mime_type,
                                "data": base64.b64encode(audio).decode("ascii"),
                            }
                        },
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "maxOutputTokens": 2048,
                "responseMimeType": "application/json",
                "responseSchema": _SCHEMA,
                "thinkingConfig": {"thinkingLevel": "low"},
            },
        }
        try:
            payload, model, latency_ms = await call_gemini(
                api_key=self.api_key, models=model_chain(self.model), body=body
            )
            data = parse_json_output(payload)
        except LLMError as exc:
            raise STTError(str(exc)) from exc
        text = data.get("text")
        spoken = data.get("language")
        return STTResult(
            text=text.strip() if isinstance(text, str) else "",
            model=model,
            language=spoken if spoken in ("pa", "en") else None,
            latency_ms=latency_ms,
        )
