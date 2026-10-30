"""Password strength policy: composition rules plus a zxcvbn entropy floor."""

import re

from zxcvbn import zxcvbn

from app.core.config import settings

_COMPOSITION_RULES: dict[str, str] = {
    "password.no_lowercase": r"[a-z]",
    "password.no_uppercase": r"[A-Z]",
    "password.no_digit": r"\d",
    "password.no_special": r"[^A-Za-z0-9]",
}


def password_errors(password: str) -> list[str]:
    """Return a list of i18n error keys; empty means the password is acceptable."""
    errors: list[str] = []
    if len(password) < settings.password_min_length:
        errors.append("password.too_short")
    if len(password) > settings.password_max_length:
        errors.append("password.too_long")
    for key, pattern in _COMPOSITION_RULES.items():
        if not re.search(pattern, password):
            errors.append(key)

    # Only run the (relatively expensive) entropy check once the shape is valid.
    if not errors and zxcvbn(password)["score"] < settings.password_min_score:
        errors.append("password.too_weak")
    return errors


def is_strong(password: str) -> bool:
    return not password_errors(password)
