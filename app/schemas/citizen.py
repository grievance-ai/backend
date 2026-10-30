"""Citizen profile: the self-declared details the assistant personalises on."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AreaType, Gender, MaritalStatus

Lang = Literal["en", "pa"]


class DistrictOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name_en: str
    name_pa: str | None


class CitizenProfileOut(BaseModel):
    name: str | None
    mobile: str | None
    preferred_language: str
    age: int | None
    gender: Gender | None
    marital_status: MaritalStatus | None
    district: DistrictOut | None
    area_type: AreaType | None
    village: str | None
    # True once the details asked for at onboarding are all filled in.
    is_complete: bool


class CitizenProfileUpdate(BaseModel):
    """Partial update: only the fields sent are changed."""

    name: str | None = Field(default=None, min_length=2, max_length=80)
    age: int | None = Field(default=None, ge=1, le=120)
    gender: Gender | None = None
    marital_status: MaritalStatus | None = None
    district_code: str | None = Field(default=None, max_length=10)
    area_type: AreaType | None = None
    village: str | None = Field(default=None, max_length=120)
    preferred_language: Lang | None = None
