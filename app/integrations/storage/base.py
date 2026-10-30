"""Storage provider interface — ported from nebryx's src/services/storage.

A provider stores a private object and hands back a key (``path``); files are
served only through a time-limited URL (presigned on S3, a local path otherwise).
Objects are laid out as ``uploads/user_<user_id>/document_<document_id>/<file>``.
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class UploadResult:
    path: str  # storage key, persisted on the Document row
    filename: str
    size: int
    content_type: str | None


def build_key(filename: str, *, user_id: object, document_id: object) -> str:
    """``uploads/user_<id>/document_<id>/<filename>`` (matches nebryx getKey)."""
    parts = ["uploads"]
    if user_id is not None:
        parts.append(f"user_{user_id}")
    if document_id is not None:
        parts.append(f"document_{document_id}")
    parts.append(filename)
    return "/".join(parts)


def unique_filename(original: str) -> str:
    """``upload-<uuid><ext>`` — never trust the client-supplied name as the key."""
    ext = PurePosixPath(original).suffix.lower()
    return f"upload-{uuid.uuid4().hex}{ext}"


class StorageProvider(ABC):
    @abstractmethod
    def upload(
        self,
        data: bytes,
        *,
        filename: str,
        content_type: str | None,
        user_id: object,
        document_id: object,
    ) -> UploadResult: ...

    @abstractmethod
    def get_url(self, path: str) -> str | None:
        """A time-limited URL for ``path``, or ``None`` if it does not exist."""

    @abstractmethod
    def delete(self, path: str) -> bool: ...

    @abstractmethod
    def exists(self, path: str) -> bool: ...
