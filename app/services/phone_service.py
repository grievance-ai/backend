"""Phone management: store a number (encrypted + blind-indexed), deliver a
verification code through the configured SMS provider, and on success record the
``phone=verified`` label via the progressive-verification engine.

Self-managed providers (mock, Twilio SMS, AWS SNS) have us generate and store
the code; Twilio Verify issues and checks it, so no code is stored — see
``integrations/sms``.
"""

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.integrations import sms
from app.models.phone import Phone
from app.models.user import User
from app.services import level_service
from app.utils.blind_index import blind_index
from app.workers.sms import send_verification_code


def _generate_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


async def list_phones(db: AsyncSession, user_id: uuid.UUID) -> list[Phone]:
    rows = await db.scalars(select(Phone).where(Phone.user_id == user_id))
    return list(rows.all())


async def create_phone(
    db: AsyncSession, user: User, *, country: str | None, number: str
) -> tuple[Phone, str | None]:
    # Twilio Verify owns the code; for every other provider we generate one.
    code = None if sms.get_provider().manages_codes else _generate_code()
    phone = Phone(
        user_id=user.id,
        country=country,
        number=number,
        number_index=blind_index(number),
        code=code,
    )
    db.add(phone)
    await db.commit()
    await db.refresh(phone)
    send_verification_code.delay(number=number, code=code)
    return phone, code


async def verify_phone(db: AsyncSession, user: User, *, phone_id: uuid.UUID, code: str) -> Phone:
    phone = await db.scalar(select(Phone).where(Phone.id == phone_id, Phone.user_id == user.id))
    if phone is None:
        raise APIError(["resource.phone.not_found"], 404)
    if phone.validated_at is not None:
        return phone
    if not sms.get_provider().check_code(number=phone.number, code=code, expected=phone.code):
        raise APIError(["resource.phone.invalid_code"], 422)

    phone.validated_at = datetime.now(UTC)
    phone.code = None
    # The level engine commits the pending phone changes, adds the private
    # phone=verified label, and re-derives the user's level (and state).
    await level_service.add_label(db, user, key="phone", value="verified")
    await db.refresh(phone)
    return phone
