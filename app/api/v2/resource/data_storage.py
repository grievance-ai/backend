"""The user's encrypted key/value storage."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import authorized_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import Envelope
from app.schemas.resource import DataStorageIn, DataStorageOut
from app.services import data_storage_service

router = APIRouter()


@router.get("/data_storage", response_model=Envelope[list[DataStorageOut]])
async def list_my_data(
    user: User = Depends(authorized_user), db: AsyncSession = Depends(get_db)
) -> Envelope[list[DataStorageOut]]:
    rows = await data_storage_service.list_items(db, user.id)
    return Envelope[list[DataStorageOut]](data=[DataStorageOut.model_validate(r) for r in rows])


@router.post(
    "/data_storage", response_model=Envelope[DataStorageOut], status_code=status.HTTP_201_CREATED
)
async def add_data(
    payload: DataStorageIn,
    user: User = Depends(authorized_user),
    db: AsyncSession = Depends(get_db),
) -> Envelope[DataStorageOut]:
    item = await data_storage_service.create_item(db, user, title=payload.title, data=payload.data)
    return Envelope[DataStorageOut](data=DataStorageOut.model_validate(item))
