"""Resource router: everything an authenticated user does to their own account."""

from fastapi import APIRouter

from app.api.v2.resource import (
    api_keys,
    citizen_profile,
    conversations,
    data_storage,
    documents,
    grievances,
    labels,
    otp,
    phones,
    profiles,
    schemes,
    staff,
    users,
)

resource_router = APIRouter()
resource_router.include_router(users.router)
resource_router.include_router(profiles.router)
resource_router.include_router(phones.router)
resource_router.include_router(documents.router)
resource_router.include_router(labels.router)
resource_router.include_router(otp.router)
resource_router.include_router(api_keys.router)
resource_router.include_router(data_storage.router)
resource_router.include_router(conversations.router)
resource_router.include_router(citizen_profile.router)
resource_router.include_router(grievances.router)
resource_router.include_router(schemes.router)
resource_router.include_router(staff.router)
