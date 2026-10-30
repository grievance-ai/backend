"""Gemini embeddings (REST ``batchEmbedContents``), reusing the LLM's API key."""

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.embeddings.base import EmbeddingError, EmbeddingProvider

logger = get_logger(__name__)

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_BATCH = 100  # texts per request


class GeminiEmbeddingProvider(EmbeddingProvider):
    name = "gemini"

    @property
    def model(self) -> str:
        return f"{settings.embedding_model}:{settings.embedding_dimensions}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not settings.gemini_api_key:
            raise EmbeddingError("GEMINI_API_KEY is not set")
        name = f"models/{settings.embedding_model}"
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            for start in range(0, len(texts), _BATCH):
                chunk = texts[start : start + _BATCH]
                body = {
                    "requests": [
                        {
                            "model": name,
                            "content": {"parts": [{"text": text}]},
                            "outputDimensionality": settings.embedding_dimensions,
                        }
                        for text in chunk
                    ]
                }
                try:
                    resp = await client.post(
                        f"{_BASE_URL}/{settings.embedding_model}:batchEmbedContents",
                        headers={"x-goog-api-key": settings.gemini_api_key},
                        json=body,
                    )
                except httpx.HTTPError as exc:
                    raise EmbeddingError(f"gemini embed failed: {exc.__class__.__name__}") from exc
                if resp.status_code != 200:
                    logger.warning("gemini_embed_error", status=resp.status_code)
                    raise EmbeddingError(f"gemini embed returned {resp.status_code}")
                rows = resp.json().get("embeddings", [])
                if len(rows) != len(chunk):
                    raise EmbeddingError("gemini embed returned the wrong number of vectors")
                vectors.extend([float(x) for x in row["values"]] for row in rows)
        return vectors
