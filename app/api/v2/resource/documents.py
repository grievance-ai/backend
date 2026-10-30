"""The user's identity documents — multipart upload stored privately, served
back as time-limited URLs."""

import uuid
from datetime import date

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import authorized_user
from app.db.session import get_db
from app.models.document import Document
from app.models.user import User
from app.schemas.common import Envelope, Message
from app.schemas.resource import DocumentOut
from app.services import document_service

router = APIRouter()


def _out(document: Document, url: str | None) -> DocumentOut:
    return DocumentOut.model_validate(document).model_copy(update={"upload": url})


@router.get("/documents/me", response_model=Envelope[list[DocumentOut]])
async def list_my_documents(
    user: User = Depends(authorized_user), db: AsyncSession = Depends(get_db)
) -> Envelope[list[DocumentOut]]:
    rows = await document_service.list_documents(db, user.id)
    return Envelope[list[DocumentOut]](
        data=[_out(doc, document_service.document_url(doc)) for doc in rows]
    )


@router.post(
    "/documents", response_model=Envelope[DocumentOut], status_code=status.HTTP_201_CREATED
)
async def add_document(
    upload: UploadFile = File(...),
    doc_type: str = Form(...),
    doc_number: str = Form(..., max_length=128),
    doc_expire: date | None = Form(default=None),
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[DocumentOut]:
    document = await document_service.create_document(
        db,
        user,
        doc_type=doc_type,
        doc_number=doc_number,
        doc_expire=doc_expire,
        file_data=await upload.read(),
        filename=upload.filename or "",
        content_type=upload.content_type,
    )
    return Envelope[DocumentOut](data=_out(document, document_service.document_url(document)))


@router.delete("/documents/{document_id}", response_model=Envelope[Message])
async def delete_my_document(
    document_id: uuid.UUID,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[Message]:
    await document_service.delete_document(db, user, document_id=document_id)
    return Envelope[Message](data=Message(message="Document deleted."))
