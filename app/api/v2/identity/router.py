"""Identity router: aggregates the public authentication endpoints."""

from fastapi import APIRouter

from app.api.v2.identity import email, meta, password, sessions, users

identity_router = APIRouter()
identity_router.include_router(sessions.router)
identity_router.include_router(users.router)
identity_router.include_router(email.router)
identity_router.include_router(password.router)
identity_router.include_router(meta.router)
