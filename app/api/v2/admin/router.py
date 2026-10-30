"""Admin router (RBAC-gated by the permissions table via ``authorized_user``)."""

from fastapi import APIRouter, Depends

from app.api.deps import authorized_user
from app.api.v2.admin import activities, permissions, restrictions, users
from app.models.user import User
from app.schemas.common import Envelope

admin_router = APIRouter()
admin_router.include_router(users.router)
admin_router.include_router(permissions.router)
admin_router.include_router(activities.router)
admin_router.include_router(restrictions.router)


@admin_router.get("/ping", response_model=Envelope[dict[str, bool]])
async def admin_ping(_user: User = Depends(authorized_user)) -> Envelope[dict[str, bool]]:
    return Envelope[dict[str, bool]](data={"pong": True})


@admin_router.post("/ping", response_model=Envelope[dict[str, bool]])
async def admin_ping_write(_user: User = Depends(authorized_user)) -> Envelope[dict[str, bool]]:
    return Envelope[dict[str, bool]](data={"pong": True})
