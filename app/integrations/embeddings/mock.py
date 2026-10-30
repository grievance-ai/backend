"""Offline embeddings for tests and local dev: hashed bag of words.

Texts that share words get similar vectors, which is enough to test ranking
without an API key. Not multilingual.
"""

import hashlib
import math
import re

from app.integrations.embeddings.base import EmbeddingProvider

DIMENSIONS = 64
_WORD = re.compile(r"\w+")


def mock_vector(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
    for word in _WORD.findall(text.lower()):
        bucket = int(hashlib.sha256(word.encode()).hexdigest(), 16) % DIMENSIONS
        vector[bucket] += 1.0
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norm for x in vector]


class MockEmbeddingProvider(EmbeddingProvider):
    name = "mock"
    calls = 0

    @property
    def model(self) -> str:
        return f"mock:{DIMENSIONS}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        MockEmbeddingProvider.calls += 1
        return [mock_vector(t) for t in texts]
