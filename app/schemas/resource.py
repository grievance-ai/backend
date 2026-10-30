"""Schemas for the resource endpoints (the authenticated user's own account)."""

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


# --- users -------------------------------------------------------------------
class UserUpdateIn(BaseModel):
    username: str | None = None
    data: dict[str, Any] | None = None


class ChangePasswordIn(BaseModel):
    old_password: str
    new_password: str


class ActivityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: str
    topic: str
    action: str
    result: str
    user_ip: str | None
    user_ip_country: str | None
    created_at: datetime


# --- profiles ----------------------------------------------------------------
class ProfileIn(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    dob: str | None = None
    address: str | None = None
    city: str | None = None
    country: str | None = None
    state: int | None = None


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    first_name: str | None
    last_name: str | None
    dob: str | None
    address: str | None
    city: str | None
    country: str | None
    state: int | None
    created_at: datetime


# --- phones ------------------------------------------------------------------
class PhoneIn(BaseModel):
    country: str | None = None
    number: str


class PhoneOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    country: str | None
    number: str
    validated_at: datetime | None
    created_at: datetime


class PhoneCreatedOut(BaseModel):
    phone: PhoneOut
    verification_code: str | None = None  # populated only outside production


class PhoneVerifyIn(BaseModel):
    phone_id: uuid.UUID
    code: str


# --- documents ---------------------------------------------------------------
# Document creation is multipart (file + form fields), parsed in the route.
class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    doc_type: str
    doc_expire: date | None
    upload: str | None
    identificator: str | None
    created_at: datetime


# --- labels ------------------------------------------------------------------
class LabelIn(BaseModel):
    key: str
    value: str


class LabelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    key: str
    value: str
    scope: str
    created_at: datetime


# --- otp ---------------------------------------------------------------------
class OtpGenerateOut(BaseModel):
    secret: str
    provisioning_uri: str
    qr_code: str


class OtpCodeIn(BaseModel):
    code: str


# --- api keys ----------------------------------------------------------------
class ApiKeyCreateIn(BaseModel):
    otp_code: str
    scope: list[str] | None = None


class ApiKeyDeleteIn(BaseModel):
    otp_code: str


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kid: str
    scope: list[str] | None
    algorithm: str
    state: str
    created_at: datetime


class ApiKeyCreatedOut(BaseModel):
    kid: str
    secret: str  # shown once, never again
    scope: list[str] | None
    algorithm: str
    state: str


# --- data storage ------------------------------------------------------------
class DataStorageIn(BaseModel):
    title: str
    data: str


class DataStorageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    data: str
    created_at: datetime
