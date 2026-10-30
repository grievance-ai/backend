"""Local-filesystem storage provider (development default).

Files are written under ``settings.upload_dir``; the "URL" is a relative
``/uploads/<path>`` reference served by the app/CDN in front of it.
"""

from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.storage.base import (
    StorageProvider,
    UploadResult,
    build_key,
    unique_filename,
)

logger = get_logger(__name__)


class LocalStorageProvider(StorageProvider):
    @property
    def _root(self) -> Path:
        return Path(settings.upload_dir)

    def upload(
        self,
        data: bytes,
        *,
        filename: str,
        content_type: str | None,
        user_id: object,
        document_id: object,
    ) -> UploadResult:
        key = build_key(unique_filename(filename), user_id=user_id, document_id=document_id)
        destination = self._root / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        logger.info("file_stored_local", path=key)
        return UploadResult(
            path=key, filename=destination.name, size=len(data), content_type=content_type
        )

    def get_url(self, path: str) -> str | None:
        if not self.exists(path):
            return None
        return f"/{path}"

    def delete(self, path: str) -> bool:
        target = self._root / path
        try:
            target.unlink()
        except FileNotFoundError:
            return False
        return True

    def exists(self, path: str) -> bool:
        return (self._root / path).is_file()
