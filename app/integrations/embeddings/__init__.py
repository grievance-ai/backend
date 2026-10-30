"""Embedding provider selection: ``EMBEDDING_PROVIDER`` (blank = ``LLM_PROVIDER``)."""

from app.core.config import settings
from app.integrations.embeddings.base import EmbeddingError, EmbeddingProvider
from app.integrations.embeddings.mock import MockEmbeddingProvider

__all__ = ["EmbeddingError", "EmbeddingProvider", "get_provider"]


def get_provider() -> EmbeddingProvider:
    if settings.embedding_provider_name == "gemini":
        from app.integrations.embeddings.gemini import GeminiEmbeddingProvider

        return GeminiEmbeddingProvider()
    return MockEmbeddingProvider()
