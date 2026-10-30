"""Shared response wrappers."""

from typing import Generic, TypeVar

from pydantic import BaseModel

DataT = TypeVar("DataT")


class Envelope(BaseModel, Generic[DataT]):
    """The uniform success envelope: ``{"success": true, "data": ...}``."""

    success: bool = True
    data: DataT


class Message(BaseModel):
    message: str


class Page(BaseModel, Generic[DataT]):
    """A paginated slice of a collection."""

    items: list[DataT]
    total: int
    page: int
    limit: int
