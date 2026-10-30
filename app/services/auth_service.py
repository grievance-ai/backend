"""Authentication business logic: registration, login, email/password flows.

Routers validate and serialize; all the rules live here. Failures raise
``APIError`` with dotted i18n keys.
"""

import datetime as dt
import secrets
import uuid
from typing import cast

import jwt
import redis.asyncio as redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import security
from app.core.activity import log_activity
from app.core.config import settings
from app.core.errors import APIError
from app.core.tokens import TokenPair, TokenService
from app.emails import dispatch
from app.integrations.recaptcha import verify_captcha
from app.models.citizen_profile import CitizenProfile
from app.models.enums import Role, UserState
from app.models.user import User
from app.services import level_service
from app.services.password_strength import password_errors
from app.services.totp import TOTPService

EMAIL_CONFIRM_TYPE = "email_confirm"
PASSWORD_RESET_TYPE = "password_reset"  # token type, not a secret  # nosec B105
_EMAIL_TOKEN_TTL = 3600  # 1 hour
_PASSWORD_TOKEN_TTL = 1800  # 30 minutes


# --- lookups -----------------------------------------------------------------
async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    return cast("User | None", await db.scalar(select(User).where(User.email == email)))


# --- registration ------------------------------------------------------------
async def register(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    username: str | None,
    captcha_response: str | None = None,
) -> User:
    if not await verify_captcha(captcha_response):
        raise APIError(["identity.captcha.invalid"], 422)
    errors = password_errors(password)
    if errors:
        raise APIError(errors, 422)

    if await get_user_by_email(db, email) is not None:
        raise APIError(["identity.user.email_taken"], 409)
    if username and await db.scalar(select(User).where(User.username == username)) is not None:
        raise APIError(["identity.user.username_taken"], 409)

    is_first = settings.first_user_superadmin and (
        await db.scalar(select(func.count()).select_from(User)) == 0
    )
    user = User(
        email=email,
        username=username,
        password_digest=security.hash_password(password),
        role="superadmin" if is_first else "member",
        state=UserState.active.value if is_first else UserState.pending.value,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    dispatch.send_confirmation_email(user, make_email_token(user))
    return user


def make_email_token(user: User) -> str:
    token, _ = security.create_token(
        user_id=str(user.id),
        token_type=EMAIL_CONFIRM_TYPE,
        ttl=_EMAIL_TOKEN_TTL,
        extra={"email": user.email},
    )
    return token


# --- login + lockout ---------------------------------------------------------
def _lockout_key(email: str, ip: str) -> str:
    return f"login_attempts:{email}:{ip}"


async def _record_failure(redis_client: redis.Redis, key: str) -> None:
    attempts = await redis_client.incr(key)
    if attempts == 1:
        await redis_client.expire(key, settings.login_lockout_ttl)


async def login(
    db: AsyncSession,
    redis_client: redis.Redis,
    *,
    email: str,
    password: str,
    otp_code: str | None,
    ip: str,
    user_agent: str | None = None,
    captcha_response: str | None = None,
) -> tuple[User, TokenPair]:
    if not await verify_captcha(captcha_response):
        raise APIError(["identity.captcha.invalid"], 422)

    def audit(action: str, result: str, *, user: User | None = None) -> None:
        log_activity(
            topic="session",
            action=action,
            result=result,
            category="identity",
            user_id=user.id if user else None,
            ip=ip,
            user_agent=user_agent,
            data={"email": email},
        )

    key = _lockout_key(email, ip)
    attempts = await redis_client.get(key)
    if attempts is not None and int(attempts) >= settings.login_max_attempts:
        audit("login.locked", "denied")
        raise APIError(["identity.session.locked"], 429)

    user = await get_user_by_email(db, email)
    if (
        user is None
        or user.password_digest is None
        or not security.verify_password(password, user.password_digest)
    ):
        await _record_failure(redis_client, key)
        audit("login", "failed", user=user)
        raise APIError(["identity.session.invalid_credentials"], 401)
    if user.state == UserState.banned.value:
        audit("login", "denied", user=user)
        raise APIError(["identity.session.banned"], 401)
    if user.state == UserState.deleted.value:
        audit("login", "denied", user=user)
        raise APIError(["identity.session.deleted"], 401)
    if user.state not in {UserState.active.value, UserState.pending.value}:
        audit("login", "denied", user=user)
        raise APIError(["identity.session.not_active"], 401)

    if user.otp:
        secret = user.otp_secret
        if not otp_code:
            audit("login.otp", "failed", user=user)
            raise APIError(["identity.session.missing_otp"], 401)
        if secret is None or not await TOTPService(redis_client).verify(
            str(user.id), secret, otp_code
        ):
            await _record_failure(redis_client, key)
            audit("login.otp", "failed", user=user)
            raise APIError(["identity.session.invalid_otp"], 401)

    await redis_client.delete(key)
    pair = await TokenService(redis_client).issue_pair(user_id=str(user.id), role=user.role)
    audit("login", "succeed", user=user)
    dispatch.send_session_create_email(user, ip=ip, user_agent=user_agent)
    return user, pair


# --- citizen mobile login (prototype) ---------------------------------------
def normalize_mobile(mobile: str) -> str:
    """Store Indian numbers in E.164 form: 9876543210 → +919876543210."""
    return f"+91{mobile[-10:]}"


async def mobile_login(
    db: AsyncSession,
    redis_client: redis.Redis,
    *,
    mobile: str,
    otp: str,
    language: str,
    ip: str,
    user_agent: str | None = None,
) -> tuple[User, TokenPair]:
    """Log a citizen in with mobile + fixed OTP, creating the account on first use.

    Prototype only (spec §5.1: no real SMS). Disabled in production.
    """
    if settings.is_production:
        raise APIError(["identity.session.mobile_login_disabled"], 403)

    e164 = normalize_mobile(mobile)

    def audit(action: str, result: str, *, user: User | None = None) -> None:
        log_activity(
            topic="session",
            action=action,
            result=result,
            category="identity",
            user_id=user.id if user else None,
            actor_role=user.role if user else None,
            ip=ip,
            user_agent=user_agent,
            data={"mobile": e164[-4:]},  # last digits only in the audit trail
        )

    key = _lockout_key(e164, ip)
    attempts = await redis_client.get(key)
    if attempts is not None and int(attempts) >= settings.login_max_attempts:
        audit("login.mobile.locked", "denied")
        raise APIError(["identity.session.locked"], 429)

    if not secrets.compare_digest(otp, settings.prototype_otp):
        await _record_failure(redis_client, key)
        audit("login.mobile", "failed")
        raise APIError(["identity.session.invalid_otp"], 401)

    user = cast("User | None", await db.scalar(select(User).where(User.mobile == e164)))
    if user is None:
        user = User(
            mobile=e164,
            role=Role.citizen.value,
            state=UserState.active.value,
            preferred_language=language,
            citizen_profile=CitizenProfile(),
        )
        db.add(user)
        audit_action = "register.mobile"
    elif user.state not in {UserState.active.value, UserState.pending.value}:
        audit("login.mobile", "denied", user=user)
        raise APIError(["identity.session.not_active"], 401)
    else:
        audit_action = "login.mobile"

    user.last_active_at = dt.datetime.now(dt.UTC)
    await db.commit()
    await db.refresh(user)
    await redis_client.delete(key)
    pair = await TokenService(redis_client).issue_pair(user_id=str(user.id), role=user.role)
    audit(audit_action, "succeed", user=user)
    return user, pair


# --- email confirmation ------------------------------------------------------
async def confirm_email(db: AsyncSession, *, token: str) -> User:
    try:
        payload = security.decode_token(token, expected_type=EMAIL_CONFIRM_TYPE)
    except jwt.InvalidTokenError as exc:
        raise APIError(["identity.email.invalid_token"], 422) from exc

    user = await db.get(User, uuid.UUID(payload["uid"]))
    if user is None:
        raise APIError(["identity.email.invalid_token"], 422)

    # Adding the email=verified label re-derives level (0→1) and activates a
    # pending account — all of that lives in the progressive-verification engine.
    await level_service.add_label(db, user, key="email", value="verified")
    return user


# --- password reset ----------------------------------------------------------
async def request_password_reset(db: AsyncSession, *, email: str) -> str | None:
    user = await get_user_by_email(db, email)
    if user is None:
        return None
    token, _ = security.create_token(
        user_id=str(user.id), token_type=PASSWORD_RESET_TYPE, ttl=_PASSWORD_TOKEN_TTL
    )
    dispatch.send_password_reset_email(user, token)
    return token


async def reset_password(
    db: AsyncSession, redis_client: redis.Redis, *, token: str, password: str
) -> User:
    errors = password_errors(password)
    if errors:
        raise APIError(errors, 422)
    try:
        payload = security.decode_token(token, expected_type=PASSWORD_RESET_TYPE)
    except jwt.InvalidTokenError as exc:
        raise APIError(["identity.password.invalid_token"], 422) from exc

    user = await db.get(User, uuid.UUID(payload["uid"]))
    if user is None:
        raise APIError(["identity.password.invalid_token"], 422)

    user.password_digest = security.hash_password(password)
    await db.commit()
    await TokenService(redis_client).invalidate_all(str(user.id))  # log out everywhere
    await db.refresh(user)
    return user


def validate_reset_token(token: str) -> bool:
    try:
        security.decode_token(token, expected_type=PASSWORD_RESET_TYPE)
    except jwt.InvalidTokenError:
        return False
    return True


def now_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat()
