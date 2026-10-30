"""Request/response schemas for the identity (authentication) endpoints."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# --- responses ---------------------------------------------------------------
class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    uid: str
    email: EmailStr | None
    mobile: str | None
    name: str | None
    preferred_language: str
    username: str | None
    role: str
    state: str
    level: int
    otp: bool
    created_at: datetime


class SessionOut(BaseModel):
    user: UserOut
    csrf_token: str


class MobileSessionOut(SessionOut):
    # False → the frontend sends the citizen to the "tell us about yourself" step.
    profile_complete: bool


class CsrfOut(BaseModel):
    csrf_token: str


class ValidityOut(BaseModel):
    valid: bool


class EmailCodeOut(BaseModel):
    message: str
    confirmation_token: str | None = None  # populated only outside production


class PasswordCodeOut(BaseModel):
    message: str
    reset_token: str | None = None  # populated only outside production


class PasswordPolicyOut(BaseModel):
    min_length: int
    max_length: int
    min_score: int


class ConfigsOut(BaseModel):
    password: PasswordPolicyOut
    captcha_provider: str
    recaptcha_site_key: str | None = None


class VersionOut(BaseModel):
    version: str
    git_tag: str
    git_sha: str


# --- requests ----------------------------------------------------------------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str
    username: str | None = None
    captcha_response: str | None = None


class MobileLoginIn(BaseModel):
    """Prototype citizen login: Indian mobile number + the fixed OTP."""

    mobile: str = Field(pattern=r"^[6-9]\d{9}$", description="10-digit Indian mobile number")
    otp: str = Field(min_length=4, max_length=6)
    language: Literal["en", "pa"] = "pa"


class LoginIn(BaseModel):
    email: EmailStr
    password: str
    otp_code: str | None = None
    captcha_response: str | None = None


class EmailGenerateIn(BaseModel):
    email: EmailStr


class EmailConfirmIn(BaseModel):
    token: str


class PasswordGenerateIn(BaseModel):
    email: EmailStr


class PasswordConfirmIn(BaseModel):
    token: str
    password: str
