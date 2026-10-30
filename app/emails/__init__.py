"""Branded transactional email rendering — ported from nebryx's email service.

An event key (e.g. ``email_confirmation``) is resolved through the mailer
registry (``config/mailer.yml``) to a per-language template path + subject,
rendered with Jinja2, falling back to ``en`` when a language is missing. The
plain-text part is derived from the HTML, exactly as nebryx does it. Templates
live under ``templates/email/<event>.<lang>.html`` and extend a shared branded
layout (EML-09: cream background, gold accent, serif type).
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.config import settings

_TEMPLATES_DIR = Path(__file__).parent / "templates" / "email"
_DEFAULT_LANG = "en"


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: str
    text: str


@lru_cache
def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


@lru_cache
def _events() -> dict[str, Any]:
    """Mailer registry keyed by event key."""
    path = Path(settings.mailer_config_path)
    data: dict[str, Any] = yaml.safe_load(path.read_text()) if path.exists() else {}
    return {event["key"]: event for event in data.get("events", [])}


_TAG_RE = re.compile(r"<[^>]*>")
_WS_RE = re.compile(r"\s+")


def _to_text(rendered_html: str) -> str:
    """Plain-text alternative: strip tags and collapse whitespace (as nebryx)."""
    return _WS_RE.sub(" ", _TAG_RE.sub("", rendered_html)).strip()


def render_event(event_key: str, language: str | None, data: dict[str, Any]) -> RenderedEmail:
    event = _events().get(event_key)
    if event is None:
        raise KeyError(f"unknown email event: {event_key}")
    lang = (language or _DEFAULT_LANG).lower()
    templates = event["templates"]
    template_config = templates.get(lang) or templates[_DEFAULT_LANG]

    rendered = _env().get_template(template_config["template_path"]).render(**data)
    return RenderedEmail(
        subject=template_config["subject"],
        html=rendered,
        text=_to_text(rendered),
    )
