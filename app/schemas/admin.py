"""Admin API request/response schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.identity import UserOut
from app.schemas.resource import LabelOut


# --- users -------------------------------------------------------------------
class AdminUserOut(UserOut):
    """A user with their labels, for the admin detail view."""

    labels: list[LabelOut] = Field(default_factory=list)


class UserStateIn(BaseModel):
    state: str


class UserRoleIn(BaseModel):
    role: str


class UserOtpIn(BaseModel):
    otp: bool  # only disabling (False) is supported


class AdminLabelIn(BaseModel):
    key: str
    value: str
    scope: str = "public"


# --- permissions -------------------------------------------------------------
class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str
    verb: str
    path: str
    action: str
    topic: str | None
    created_at: datetime


class PermissionCreateIn(BaseModel):
    role: str
    verb: str
    path: str
    action: str
    topic: str | None = None


class PermissionUpdateIn(BaseModel):
    role: str | None = None
    verb: str | None = None
    path: str | None = None
    action: str | None = None
    topic: str | None = None


# --- restrictions ------------------------------------------------------------
class RestrictionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: str
    scope: str
    value: str
    code: int | None
    state: str
    created_at: datetime


class RestrictionCreateIn(BaseModel):
    category: str
    scope: str
    value: str
    code: int | None = None
    state: str = "enabled"


class RestrictionUpdateIn(BaseModel):
    value: str | None = None
    code: int | None = None
    state: str | None = None


# --- activities --------------------------------------------------------------
class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID | None
    target_uid: str | None
    category: str
    user_ip: str | None
    user_ip_country: str | None
    user_agent: str | None
    topic: str
    action: str
    result: str
    data: dict[str, Any] | None
    created_at: datetime
