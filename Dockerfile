# syntax=docker/dockerfile:1
#
# Image for the Xuanwu auth server. The same image runs the api, the Celery
# worker, and Celery beat — only the compose `command` differs (one process per
# container, freyno/Barong-style). Everything (Python, deps, tooling) lives
# inside the image; the host never needs Python.

# ---- builder: resolve + install deps into an isolated venv ----
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# uv = fast resolver/installer; build-time only (never shipped in the runtime).
RUN pip install --no-cache-dir "uv>=0.5,<0.6"

# Dependency layer — cached until requirements.lock changes. Installs into a
# self-contained venv we copy wholesale into the runtime stage.
COPY requirements.lock ./
RUN uv venv /opt/venv \
    && VIRTUAL_ENV=/opt/venv uv pip install --no-cache -r requirements.lock

# ---- runtime: just the venv + app, running as a non-root user ----
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

# Non-root runtime user (freyno/Barong run as 'app').
RUN useradd --create-home --uid 1000 app

COPY --chown=app:app . .
# Mount point for local uploads; a fresh named volume inherits this owner.
RUN mkdir -p /app/uploads && chown app:app /app/uploads
USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
