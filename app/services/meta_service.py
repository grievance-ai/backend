"""Builders for the public metadata endpoints (configs, version, time).

Shared by the identity ``meta`` router and the ``public`` router so the
client-safe configuration is defined in exactly one place.
"""

import datetime as dt

from app.core.config import settings
from app.schemas.identity import ConfigsOut, PasswordPolicyOut, VersionOut


def build_configs() -> ConfigsOut:
    """Return client-safe configuration (no secrets)."""
    return ConfigsOut(
        password=PasswordPolicyOut(
            min_length=settings.password_min_length,
            max_length=settings.password_max_length,
            min_score=settings.password_min_score,
        ),
        captcha_provider=settings.captcha_provider,
        recaptcha_site_key=settings.recaptcha_site_key or None,
    )


def build_version() -> VersionOut:
    """Return build/version metadata (populated by CI at build time)."""
    return VersionOut(
        version=settings.app_version,
        git_tag=settings.git_tag,
        git_sha=settings.git_sha,
    )


def server_time_iso() -> str:
    """Return the current server time as an ISO-8601 UTC string."""
    return dt.datetime.now(dt.UTC).isoformat()
