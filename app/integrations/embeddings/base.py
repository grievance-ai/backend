"""Embedding provider interface: text in, vectors out (spec §8: swappable services).

Used to shortlist the schemes relevant to a citizen's question. Vectors from one
provider/model are only comparable with each other, so callers store the model
name with each vector.
"""

from abc import ABC, abstractmethod


class EmbeddingError(RuntimeError):
    """The provider failed (network, quota, bad response)."""


class EmbeddingProvider(ABC):
    name: str

    @property
    @abstractmethod
    def model(self) -> str:
        """Identifies the vector space; stored with every vector."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """One vector per text, in order. Raise ``EmbeddingError`` on failure."""
