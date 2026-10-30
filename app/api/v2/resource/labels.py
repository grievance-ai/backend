"""The user's public labels (private labels are system-managed)."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import authorized_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.resource import LabelIn, LabelOut
from app.services import label_service

router = APIRouter()


@router.get("/labels", response_model=Envelope[list[LabelOut]])
async def list_my_labels(
    user: User = Depends(authorized_user), db: AsyncSession = Depends(get_db)
) -> Envelope[list[LabelOut]]:
    rows = await label_service.list_public_labels(db, user.id)
    return Envelope[list[LabelOut]](data=[LabelOut.model_validate(r) for r in rows])


@router.post("/labels", response_model=Envelope[LabelOut], status_code=status.HTTP_201_CREATED)
async def add_label(
    payload: LabelIn,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[LabelOut]:
    label = await label_service.create_public_label(db, user, key=payload.key, value=payload.value)
    return Envelope[LabelOut](data=LabelOut.model_validate(label))
