"""Identity documents: store the metadata (encrypted number + blind index) and
the file itself through the storage provider, served back only as a time-limited
URL. Ported from nebryx's documents route + storage service.

Verifying a document (which adds the ``document=verified`` label and lifts the
user to level 3) is an admin action handled in the admin API, not here.
"""

import uuid
from datetime import date
from pathlib import PurePosixPath

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import APIError
from app.integrations import storage
from app.models.document import Document
from app.models.user import User
from app.utils.blind_index import blind_index


def _validate_upload(*, filename: str, size: int) -> None:
    if not filename:
        raise APIError(["resource.document.upload_required"], 422)
    extension = PurePosixPath(filename).suffix.lstrip(".").lower()
    if extension not in settings.upload_extensions_list:
        raise APIError(["resource.document.invalid_extension"], 422)
    if size > settings.upload_max_size:
        raise APIError(["resource.document.too_large"], 422)


async def list_documents(db: AsyncSession, user_id: uuid.UUID) -> list[Document]:
    rows = await db.scalars(select(Document).where(Document.user_id == user_id))
    return list(rows.all())


def document_url(document: Document) -> str | None:
    """The presigned/relative URL for a stored document, or ``None``."""
    if not document.upload:
        return None
    return storage.get_provider().get_url(document.upload)


async def create_document(
    db: AsyncSession,
    user: User,
    *,
    doc_type: str,
    doc_number: str,
    doc_expire: date | None,
    file_data: bytes,
    filename: str,
    content_type: str | None,
) -> Document:
    _validate_upload(filename=filename, size=len(file_data))

    # Persist the row first so the storage key can include the document id, then
    # attach the upload; if storage fails, roll the row back (as nebryx does).
    document = Document(
        user_id=user.id,
        doc_type=doc_type,
        doc_number=doc_number,
        doc_number_index=blind_index(doc_number),
        doc_expire=doc_expire,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    try:
        result = storage.get_provider().upload(
            file_data,
            filename=filename,
            content_type=content_type,
            user_id=user.id,
            document_id=document.id,
        )
    except Exception as exc:
        await db.delete(document)
        await db.commit()
        raise APIError(["resource.document.upload_failed"], 500) from exc

    document.upload = result.path
    await db.commit()
    await db.refresh(document)
    return document


async def delete_document(db: AsyncSession, user: User, *, document_id: uuid.UUID) -> None:
    document = await db.scalar(
        select(Document).where(Document.id == document_id, Document.user_id == user.id)
    )
    if document is None:
        raise APIError(["resource.document.not_found"], 404)
    if document.upload:
        storage.get_provider().delete(document.upload)
    await db.delete(document)
    await db.commit()
