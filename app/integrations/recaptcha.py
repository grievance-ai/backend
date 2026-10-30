"""Google reCAPTCHA verification — ported from nebryx's captchaService.

Disabled unless ``CAPTCHA_PROVIDER=recaptcha``; when enabled, a missing token
fails and a present token is checked against Google's siteverify endpoint. If no
secret is configured the check passes (so it never hard-blocks a misconfigured
non-prod environment), matching nebryx.
"""

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_VERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"


async def verify_captcha(response: str | None) -> bool:
    if settings.captcha_provider.lower() != "recaptcha":
        return True
    if not response:
        return False
    if not settings.recaptcha_secret:
        return True
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            result = await client.post(
                _VERIFY_URL,
                data={"secret": settings.recaptcha_secret, "response": response},
            )
        return bool(result.json().get("success") is True)
    except Exception:
        logger.warning("captcha_verify_failed", exc_info=True)
        return False
