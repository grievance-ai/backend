"""Storage provider selection — ported from nebryx's storageService.

``get_provider()`` returns the provider named by ``STORAGE_PROVIDER``: ``local``
(default) writes to disk; ``s3`` targets S3 / MinIO / R2.
"""

from app.core.config import settings
from app.integrations.storage.base import StorageProvider, UploadResult
from app.integrations.storage.local import LocalStorageProvider
from app.integrations.storage.s3 import S3StorageProvider

__all__ = ["StorageProvider", "UploadResult", "get_provider"]


def get_provider() -> StorageProvider:
    if settings.storage_provider.lower() == "s3":
        return S3StorageProvider()
    return LocalStorageProvider()
