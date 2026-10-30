"""S3 / S3-compatible (MinIO, Cloudflare R2) storage provider.

Objects are private and server-side encrypted; access is granted only through a
short-lived presigned GET URL. Ported from nebryx's s3Storage.js.
"""

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.storage.base import (
    StorageProvider,
    UploadResult,
    build_key,
    unique_filename,
)

logger = get_logger(__name__)


class S3StorageProvider(StorageProvider):
    def _client(self) -> Any:
        import boto3

        return boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            aws_access_key_id=settings.s3_access_key or None,
            aws_secret_access_key=settings.s3_secret_key or None,
            region_name=settings.s3_region,
        )

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
        params: dict[str, Any] = {"Bucket": settings.s3_bucket, "Key": key, "Body": data}
        if content_type:
            params["ContentType"] = content_type
        if settings.s3_sse:
            params["ServerSideEncryption"] = settings.s3_sse
        self._client().put_object(**params)
        logger.info("file_stored_s3", path=key)
        return UploadResult(
            path=key, filename=key.rsplit("/", 1)[-1], size=len(data), content_type=content_type
        )

    def get_url(self, path: str) -> str | None:
        try:
            url: str = self._client().generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.s3_bucket, "Key": path},
                ExpiresIn=settings.s3_url_expiration,
            )
        except Exception:
            logger.warning("s3_presign_failed", path=path, exc_info=True)
            return None
        return url

    def delete(self, path: str) -> bool:
        try:
            self._client().delete_object(Bucket=settings.s3_bucket, Key=path)
        except Exception:
            logger.warning("s3_delete_failed", path=path, exc_info=True)
            return False
        return True

    def exists(self, path: str) -> bool:
        try:
            self._client().head_object(Bucket=settings.s3_bucket, Key=path)
        except Exception:
            return False
        return True
