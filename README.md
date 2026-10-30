# Xuanwu

A self-hosted **authentication and authorization server** built with FastAPI,
MySQL 8, Redis, and Celery.

It provides token-based auth (RS256 JWT in httpOnly cookies with refresh-token
rotation), role-based access control, API-key (HMAC) access for machine clients,
TOTP two-factor auth, encrypted PII at rest with searchable blind indexes,
progressive identity verification (levels and labels), rate limiting, and an
immutable audit trail.

Named after Xuanwu (玄武), the Black Tortoise, guardian of the North.

---

## Table of contents

- [Features](#features)
- [Tech stack](#tech-stack)
- [Requirements](#requirements)
- [Quickstart](#quickstart)
- [Configuration](#configuration)
- [Command reference](#command-reference)
  - [Make targets](#make-targets)
  - [Operator console](#operator-console)
  - [Docker and Compose](#docker-and-compose)
  - [Database migrations (Alembic)](#database-migrations-alembic)
  - [Database and Redis shells](#database-and-redis-shells)
  - [Quality gates](#quality-gates)
  - [Dependencies](#dependencies)
- [Background workers](#background-workers)
- [API reference](#api-reference)
- [Authentication and authorization](#authentication-and-authorization)
- [Project layout](#project-layout)
- [Testing](#testing)
- [Production deployment](#production-deployment)
- [Contributing](#contributing)
- [License](#license)

---

## Features

- **JWT auth in httpOnly cookies** (RS256). Login issues a 15-minute access
  token and a 7-day refresh token. Refresh tokens rotate on use and can be
  revoked individually (logout) or all at once (password change, 2FA toggle,
  ban).
- **CSRF protection** via a double-submit token on every state-changing request.
- **API-key access for machines** using HMAC-SHA256 request signing with a
  nonce replay window. API-key use requires 2FA on the account.
- **Role-based access control** driven by a `permissions` table (role, verb,
  path-prefix, action) plus a YAML allow/block list, cached in Redis.
- **TOTP two-factor auth** (`pyotp`) with QR provisioning and a Redis replay
  guard.
- **Encrypted PII at rest** (Fernet) with deterministic blind indexes so
  encrypted fields like phone and document number stay searchable.
- **Progressive verification**: verifying email, phone, and identity documents
  adds labels that raise the user's level (0 to 3) and drive account state.
- **Immutable audit trail** written asynchronously through Celery.
- **Perimeter hardening**: IP/subnet/country restrictions, rate limiting,
  optional reCAPTCHA, secure response headers, login lockout.
- **Transactional email** with branded Jinja2 templates, multi-language
  support, background delivery, and automatic retry. Pluggable providers:
  **SMTP**, **SendGrid**, or a mock catcher for development.
- **SMS phone verification** with pluggable providers: **Twilio SMS**,
  **Twilio Verify**, **AWS SNS**, or a mock provider for development.
- **Object storage** for documents with **AWS S3** and **Cloudflare R2**
  support (and a local filesystem backend), private by default and served over
  time-limited presigned URLs.

## Tech stack

| Concern         | Choice                                            |
|-----------------|---------------------------------------------------|
| Web framework   | FastAPI                                            |
| Database        | MySQL 8 (SQLAlchemy 2.0 async + `asyncmy`)         |
| Migrations      | Alembic (sync `pymysql` driver)                    |
| Cache / state   | Redis (token state, RBAC cache, rate limits)       |
| Background jobs | Celery (Redis broker) + Celery beat scheduler      |
| Auth            | `pyjwt` (RS256), `passlib[bcrypt]`, `pyotp`         |
| Email           | SMTP / SendGrid support                            |
| SMS             | Twilio SMS / Twilio Verify / AWS SNS support       |
| Object storage  | AWS S3 / Cloudflare R2 / local filesystem support  |
| Captcha         | Google reCAPTCHA support                           |
| Packaging       | Docker, Docker Compose                             |
| Tooling         | ruff, mypy (strict), bandit, pip-audit, pytest     |

The application, namespaced under `/api/v2/xuanwu/`, is backend-only.

## Requirements

- Docker and Docker Compose.

That is the entire requirement list. The whole toolchain (Python,
dependencies, linters, type checker, tests) lives inside the image, so no
local Python install is needed or expected. Every command below runs in a
container.

---

## Quickstart

From a fresh clone:

```bash
cp .env.example .env                          # local configuration
make build                                    # build the image
make migrate                                  # create the database schema
make seed                                     # default RBAC permissions + levels
make superadmin EMAIL=admin@example.com       # bootstrap an admin (prompts for password)
make stack                                    # start the whole stack
```

`make stack` starts MySQL, Redis, the API, the Celery worker, Celery beat,
MailHog (email catcher), and MinIO (S3-compatible storage).

Then log in:

```bash
curl -i -X POST http://localhost:8000/api/v2/xuanwu/identity/sessions \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"<the password you set>"}'
```

The response sets `access_token`, `refresh_token`, and `csrf_token` cookies and
returns the user plus the CSRF token in the body.

Useful URLs once the stack is up:

| URL                                                   | What it is                    |
|-------------------------------------------------------|-------------------------------|
| http://localhost:8000/docs                            | Swagger UI                    |
| http://localhost:8000/redoc                           | ReDoc                         |
| http://localhost:8000/openapi.json                    | OpenAPI schema                |
| http://localhost:8000/health                          | Liveness probe                |
| http://localhost:8000/health/ready                    | DB + Redis readiness probe    |
| http://localhost:8000/api/v2/xuanwu/public/ping       | Public namespace ping         |
| http://localhost:8025                                 | MailHog UI (sent email)       |
| http://localhost:9001                                 | MinIO console                 |

---

## Configuration

All configuration comes from environment variables, loaded through
`pydantic-settings` (`app/core/config.py`). In development they are read from
`.env`. **`.env.example` documents every variable**; copy it and adjust.

The variables that must be set for a real deployment:

| Variable             | Purpose                                                        |
|----------------------|----------------------------------------------------------------|
| `APP_ENV`            | `development`, `staging`, or `production`                       |
| `DATABASE_URL`       | Async MySQL URL, e.g. `mysql+asyncmy://user:pass@host:3306/db`  |
| `DATABASE_URL_SYNC`  | Sync MySQL URL for Alembic, `mysql+pymysql://...`               |
| `REDIS_URL`          | Redis connection for token state, cache, rate limits           |
| `CELERY_BROKER_URL`  | Redis broker for Celery                                         |
| `CELERY_RESULT_BACKEND` | Redis backend for Celery results                            |
| `SECRET_KEY`         | Master secret; derives the field-encryption key                |
| `BLIND_INDEX_KEY`    | Key for deterministic blind indexes on encrypted columns       |
| `JWT_PRIVATE_KEY_PATH` / `JWT_PUBLIC_KEY_PATH` | RS256 keypair paths                  |

Other notable groups (see `.env.example` for defaults and the full set):

- **Host ports** for Compose: `API_HOST_PORT` (8000), `DB_HOST_PORT` (3307),
  `REDIS_HOST_PORT` (6380), `MAILHOG_SMTP_PORT` (1025), `MAILHOG_UI_PORT`
  (8025), `MINIO_PORT` (9000), `MINIO_CONSOLE_PORT` (9001). The host side is
  configurable so it never clashes with other local stacks; containers always
  talk to each other on the standard ports over the Compose network.
- **Token policy**: `ACCESS_TOKEN_TTL`, `REFRESH_TOKEN_TTL`,
  `LOGIN_MAX_ATTEMPTS`, `LOGIN_LOCKOUT_TTL`.
- **Cookies**: `COOKIE_SECURE` (set `true` behind HTTPS), `COOKIE_SAMESITE`,
  `COOKIE_DOMAIN`.
- **Password policy**: `PASSWORD_MIN_LENGTH`, `PASSWORD_MAX_LENGTH`,
  `PASSWORD_MIN_SCORE` (zxcvbn floor).
- **Providers**: `EMAIL_PROVIDER` (mock / smtp / sendgrid), `SMS_PROVIDER`
  (mock / twilio_sms / twilio_verify / aws_sns), `STORAGE_PROVIDER`
  (local / s3), `CAPTCHA_PROVIDER` (none / recaptcha), `GEOIP_PROVIDER`
  (none / maxmind).
- **Hardening**: `RATE_LIMIT_ENABLED`, `RATE_LIMIT_DEFAULT`,
  `RATE_LIMIT_LOGIN`, `HSTS_ENABLED`.

The RS256 JWT keypair is auto-generated on first use in development. In
production it must be provided at the configured paths; generate one with
`make keys`.

---

## Command reference

> `docker compose run --rm api ...` auto-starts db and redis first (they have
> healthchecks). Add `--no-deps` to skip that when they are already running,
> which is faster for lint/type checks that do not touch the database.

### Make targets

`make help` lists everything. The targets:

| Target        | What it does                                                   |
|---------------|---------------------------------------------------------------|
| `make build`  | Build the API image                                           |
| `make up`     | Start just the API (plus db + redis)                          |
| `make stack`  | Start the whole stack (db, redis, api, worker, beat, mailhog, minio) |
| `make down`   | Stop everything (keeps the data volume)                       |
| `make migrate`| Apply database migrations (`alembic upgrade head`)           |
| `make seed`   | Seed default permissions and levels (idempotent)             |
| `make keys`   | Generate the RS256 JWT keypair                               |
| `make superadmin EMAIL=... [PASSWORD=...]` | Create a superadmin            |
| `make worker` | Run a Celery worker                                          |
| `make beat`   | Run the Celery beat scheduler                                |
| `make lint`   | `ruff check`                                                 |
| `make fmt`    | `ruff format` (writes changes)                              |
| `make fmt-check` | `ruff format --check`                                     |
| `make type`   | `mypy` (strict)                                             |
| `make test`   | `pytest`                                                    |
| `make cov`    | `pytest` with a coverage report                            |
| `make security` | `bandit` + `pip-audit`                                    |
| `make check`  | Run all gates: lint + format check + type + test           |
| `make lock`   | Regenerate `requirements.lock` from `pyproject.toml`       |

### Operator console

The console (`python -m app.console`) bootstraps and maintains an install:

```bash
# Generate the RS256 JWT keypair (use --force to rotate; rotating invalidates all tokens)
docker compose run --rm api python -m app.console generate-keys
docker compose run --rm api python -m app.console generate-keys --force

# Seed default RBAC permissions and verification levels (idempotent)
docker compose run --rm api python -m app.console seed

# Create an active superadmin (bypasses the registration flow)
docker compose run --rm api python -m app.console create-superadmin \
  --email admin@example.com [--username admin] [--password ...]
```

If `--password` is omitted, `create-superadmin` prompts for it interactively.

### Docker and Compose

```bash
docker compose build api          # build the image
docker compose up                 # whole stack in the foreground
docker compose up -d              # whole stack in the background
docker compose up api             # just the API (plus db + redis)
docker compose logs -f api        # follow API logs
docker compose ps                 # what is running
docker compose restart api        # restart the API
docker compose down               # stop everything (keeps the data volume)
docker compose down -v            # stop and wipe the database/storage volumes
```

### Database migrations (Alembic)

```bash
docker compose run --rm api alembic upgrade head        # apply all migrations
docker compose run --rm api alembic current -v          # where the DB is now
docker compose run --rm api alembic heads               # latest revision in code
docker compose run --rm api alembic history -v          # full history
docker compose run --rm api alembic check               # models vs DB in sync?
docker compose run --rm api alembic downgrade -1        # one step back
docker compose run --rm api alembic downgrade base      # drop everything

# After changing a model:
docker compose run --rm api alembic revision --autogenerate -m "describe change"
# review the generated file under alembic/versions/, then upgrade.
```

The schema is in sync when `alembic current` equals `alembic heads` and
`alembic check` reports no new operations.

### Database and Redis shells

```bash
# MySQL (database xuanwu, user rv / password rv in dev)
docker compose exec db mysql -urv -prv xuanwu
docker compose exec db mysql -urv -prv xuanwu -e "SHOW TABLES;"

# Redis
docker compose exec redis redis-cli
```

### Quality gates

These are exactly what CI runs:

```bash
docker compose run --rm --no-deps api ruff check .            # lint
docker compose run --rm --no-deps api ruff format --check .   # format check
docker compose run --rm --no-deps api mypy                    # type check (strict)
docker compose run --rm --no-deps api bandit -q -c pyproject.toml -r app
docker compose run --rm --no-deps api pip-audit --ignore-vuln CVE-2025-65896
docker compose run --rm api pytest -q                         # tests (needs db + redis)
```

Run `pytest` without `--no-deps` so db and redis start; the integration tests
skip when no database is reachable. `make check` and `make security` wrap these.

> `CVE-2025-65896` (asyncmy) has no fixed release yet; it is tracked and
> explicitly ignored.

### Dependencies

```bash
# Edit pyproject.toml, then regenerate the pinned lockfile and rebuild:
make lock
make build
```

---

## Background workers

Processing is split one-process-per-container:

- **worker** (`celery ... worker`) runs tasks: transactional email, SMS,
  and immutable audit writes.
- **beat** (`celery ... beat`) fires scheduled jobs. Today that is a daily
  sweep (`maintenance.clean_expired_tokens`, 03:00 UTC) that prunes orphaned
  refresh-token references from Redis. The schedule lives in
  `app/workers/celery_app.py`.

```bash
docker compose up worker
docker compose up beat
```

In development you can skip the worker entirely by setting
`CELERY_TASK_ALWAYS_EAGER=true`, which runs tasks inline in the API process.

---

## API reference

Everything is versioned and namespaced under `/api/v2/xuanwu/`. Responses use a
uniform envelope: `{"success": true, "data": ...}` or
`{"success": false, "errors": [...]}`.

`/health` and `/health/ready` are served at the application root (outside the
namespace) as load-balancer probes and stay reachable during maintenance mode.

### Namespaces and auth

| Group     | Path prefix                | Auth                                          |
|-----------|----------------------------|-----------------------------------------------|
| public    | `/api/v2/xuanwu/public/`   | none                                          |
| identity  | `/api/v2/xuanwu/identity/` | none (the authentication endpoints)           |
| resource  | `/api/v2/xuanwu/resource/` | access cookie + CSRF, or API-key HMAC         |
| admin     | `/api/v2/xuanwu/admin/`    | access cookie + role check (admin/superadmin) |

### public

| Method | Path        | Purpose                          |
|--------|-------------|----------------------------------|
| GET    | `/ping`     | Liveness                         |
| GET    | `/time`     | Server time                      |
| GET    | `/version`  | App version / build info         |
| GET    | `/configs`  | Client-safe config (policy, keys)|

### identity

| Method | Path                      | Purpose                                  |
|--------|---------------------------|------------------------------------------|
| POST   | `/users`                  | Register; sets auth cookies              |
| POST   | `/sessions`               | Log in; sets auth cookies                |
| POST   | `/sessions/refresh`       | Rotate tokens; sets new cookies          |
| DELETE | `/sessions`               | Log out; revokes refresh token           |
| POST   | `/email/generate_code`    | Send an email confirmation code          |
| POST   | `/email/confirm_code`     | Confirm email (adds `email=verified`)    |
| POST   | `/password/generate_code` | Start a password reset                   |
| POST   | `/password/confirm_code`  | Complete a password reset                |
| GET    | `/password/validate`      | Check password strength                  |
| GET    | `/ping` `/time` `/version` `/configs` | Service metadata             |

### resource (the authenticated user acting on themselves)

| Method | Path                          | Purpose                                |
|--------|-------------------------------|----------------------------------------|
| GET    | `/users/me`                   | Current user                           |
| PUT    | `/users/me`                   | Update profile data                    |
| PUT    | `/users/password`             | Change password                        |
| GET    | `/users/activity/{topic}`     | Own activity log by topic              |
| GET    | `/profiles/me`                | Own profile (decrypted)                |
| POST   | `/profiles`                   | Create/update profile (encrypted)      |
| GET    | `/phones/me`                  | Own phones                             |
| POST   | `/phones`                     | Add a phone, request a code            |
| POST   | `/phones/verify`              | Verify a phone code                    |
| GET    | `/documents/me`               | Own documents (presigned URLs)         |
| POST   | `/documents`                  | Upload a document (multipart)          |
| DELETE | `/documents/{document_id}`    | Delete a document                      |
| GET    | `/labels`                     | Own public labels                      |
| POST   | `/labels`                     | Add a public label                     |
| POST   | `/otp/generate_qrcode`        | Begin 2FA setup (QR)                    |
| POST   | `/otp/enable`                 | Enable 2FA (revokes all sessions)      |
| POST   | `/otp/disable`                | Disable 2FA                            |
| GET    | `/api_keys`                   | List API keys                          |
| POST   | `/api_keys`                   | Create an API key (2FA-gated; secret shown once) |
| DELETE | `/api_keys/{kid}`             | Revoke an API key                      |
| GET    | `/data_storage`               | List encrypted key-value entries       |
| POST   | `/data_storage`               | Create an encrypted key-value entry    |

### admin (admin/superadmin via RBAC)

| Method | Path                          | Purpose                                |
|--------|-------------------------------|----------------------------------------|
| GET    | `/users`                      | List/filter users                      |
| GET    | `/users/{uid}`                | Get a user with labels                 |
| PUT    | `/users/{uid}/state`          | Change account state                   |
| PUT    | `/users/{uid}/role`           | Change role                            |
| PUT    | `/users/{uid}/otp`            | Disable a user's 2FA                    |
| POST   | `/users/{uid}/labels`         | Add a label (can verify email/phone/document) |
| DELETE | `/users/{uid}/labels`         | Remove a label                         |
| GET    | `/permissions`                | List permissions (superadmin)          |
| POST   | `/permissions`                | Create a permission (superadmin)       |
| PUT    | `/permissions/{id}`           | Update a permission (superadmin)       |
| DELETE | `/permissions/{id}`           | Delete a permission (superadmin)       |
| GET    | `/restrictions`               | List restrictions (superadmin)         |
| POST   | `/restrictions`               | Create a restriction (superadmin)      |
| PUT    | `/restrictions/{id}`          | Update a restriction (superadmin)      |
| DELETE | `/restrictions/{id}`          | Delete a restriction (superadmin)      |
| GET    | `/activities`                 | List/filter the audit log              |

Admin paths are hidden from the public OpenAPI schema unless the requester is a
logged-in admin. This reduces information disclosure; it is not the access
control. The routes are RBAC-protected regardless.

---

## Authentication and authorization

- **Browser auth** uses RS256 JWTs in httpOnly cookies: a 15-minute access
  token and a 7-day refresh token. The access token authenticates requests; the
  refresh token rotates at `POST /sessions/refresh`. Each refresh token's `jti`
  is tracked in Redis so sessions can be revoked individually or all at once.
- **CSRF**: a readable `csrf_token` cookie is minted at login and must be echoed
  in the `X-CSRF-Token` header on every state-changing request (compared in
  constant time).
- **API-key auth** for machine clients: send `X-Auth-Apikey`, `X-Auth-Nonce`,
  and `X-Auth-Signature` (HMAC-SHA256 over the nonce and key id). The nonce has
  a short replay window. API-key use requires 2FA enabled on the account.
- **RBAC**: a `permissions` table (role, verb, path-prefix, action of
  ACCEPT/DROP/AUDIT) is matched by HTTP verb and path prefix, on top of a YAML
  allow/block list. Permission lookups are cached in Redis for five minutes and
  busted on change.
- **Levels and labels**: confirming email, phone, and identity documents adds
  private labels that raise the user's level (0 to 3). Labels also drive account
  state (active, pending, banned, locked, deleted). Banning or deleting an
  account revokes all of its refresh tokens.

---

## Project layout

```
.
├── app/
│   ├── main.py             # application factory, health probes, middleware
│   ├── console.py          # operator CLI (generate-keys, seed, create-superadmin)
│   ├── core/               # config, security, tokens, csrf, encryption, rbac, errors
│   ├── db/                 # base, sessions (async + sync), seeds
│   ├── models/             # SQLAlchemy models (13 entities) + enums
│   ├── schemas/            # Pydantic request/response schemas
│   ├── api/                # routers (api/v2/{public,identity,resource,admin}) + deps
│   ├── services/           # business logic (auth, profile, otp, level, ...)
│   ├── workers/            # Celery app + tasks (email, sms, activity, maintenance)
│   ├── queries/            # filter/query builders
│   ├── emails/             # branded templates + rendering
│   └── integrations/       # email, sms, storage, recaptcha, geoip providers
├── alembic/versions/       # database migrations
├── config/                 # authz rules, auth/mailer YAML, generated JWT keys
├── tests/                  # pytest suite (models, core, services, workers, api)
├── Dockerfile              # multi-stage image (non-root); runs api / worker / beat
├── docker-compose.yml      # db, redis, api, worker, beat, mailhog, minio
├── docker-compose.prod.yml # production overrides (no mounts, worker pool)
├── Makefile                # command wrappers (all run in Docker)
├── COMMANDS.md             # command cheat sheet
├── CONTRIBUTING.md         # contribution workflow
├── pyproject.toml          # dependencies + ruff/mypy/pytest/bandit config
├── requirements.lock       # fully-pinned dependencies
└── .env.example            # documented environment template
```

---

## Testing

```bash
make test       # full suite
make cov        # suite with a coverage report
```

Tests use `httpx.AsyncClient`, a per-test database engine, and `fakeredis`.
External services (email, SMS, storage, captcha, GeoIP) are mocked by autouse
fixtures, and Celery runs eagerly. Integration tests skip automatically when no
database is reachable, so run them with db and redis up (the default
`docker compose run --rm api pytest` does this). Tests are organised under
`tests/{models,core,services,workers,api}/` mirroring the application.

---

## Production deployment

Layer the production override on top of the base Compose file:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

The override drops source bind-mounts and hot reload, runs a uvicorn worker
pool and a concurrent Celery worker, and excludes the dev-only MailHog and MinIO
services. For a real deployment also:

- Set `APP_ENV=production`, `COOKIE_SECURE=true`, and `HSTS_ENABLED=true`.
- Provide strong `SECRET_KEY` and `BLIND_INDEX_KEY` values.
- Generate and mount an RS256 keypair (`make keys`); the app refuses to start
  in production without one.
- Point `DATABASE_URL`, `REDIS_URL`, and the email/SMS/storage providers at real
  infrastructure.
- Run `alembic upgrade head` and seed permissions/levels before first use.

CI (`.github/workflows/ci.yml`) builds the image and runs the full gate chain on
every push and pull request: lint, format check, type check, security, then
migrate and test.

---

## Contributing

See `CONTRIBUTING.md`. In short: everything runs in Docker, services hold the
logic (routers only validate and serialize), and `make check` plus
`make security` must be green before a pull request.

---

## License

MIT. See `LICENSE`.
