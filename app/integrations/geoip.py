"""GeoIP country resolution with a pluggable provider.

The default provider is ``none`` (returns ``None``), so the stack runs fully
offline. Set ``GEOIP_PROVIDER=maxmind`` and ``GEOIP_DB_PATH`` to a local MaxMind
GeoLite2-Country database to resolve real countries; ``geoip2`` is imported
lazily so it is only required when that provider is enabled. Private and
loopback addresses always resolve to ``None``.
"""

import ipaddress
from functools import lru_cache
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_reserved)


@lru_cache
def _maxmind_reader(db_path: str) -> Any:
    import geoip2.database  # optional dependency; required only when enabled

    return geoip2.database.Reader(db_path)


def _maxmind_country(ip: str) -> str | None:
    try:
        response = _maxmind_reader(settings.geoip_db_path).country(ip)
    except Exception:
        logger.warning("geoip_lookup_failed", exc_info=True)
        return None
    country: str | None = response.country.iso_code
    return country


def resolve_country(ip: str | None) -> str | None:
    """Return the ISO-3166 alpha-2 country for a public IP, else ``None``."""
    if not ip or not _is_public(ip):
        return None
    if settings.geoip_provider.lower() == "maxmind":
        return _maxmind_country(ip)
    return None
