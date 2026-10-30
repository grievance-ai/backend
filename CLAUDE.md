# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project context

Xuanwu is a self-hosted FastAPI auth/authz server (MySQL, Redis, Celery). It is the backend of the Grievance and Scheme Assistant prototype and is extended in place for product features. Product rules and the spec pointer are in `../CLAUDE.md`.

Backend-specific notes:
- The `User` model (`app/models/user.py`) is email-keyed. It has to be adapted to use mobile number as the login identifier.
- Keep `SMS_PROVIDER=mock`, because the prototype sends no real SMS.
- New STT/LLM services should follow the provider pattern in `app/integrations/` (described below).

## Commands

Everything runs inside Docker; no host Python. Run commands from this directory. `make help` lists all targets.

```bash
cp .env.example .env                       # once
make build                                 # build api image
make keys                                  # generate RS256 JWT keypair (config/)
make migrate                               # alembic upgrade head
make seed                                  # RBAC permissions + levels (idempotent)
make superadmin EMAIL=admin@example.com
make up                                    # API → http://localhost:8000 (/docs, /health)
make stack                                 # db, redis, api, worker, beat, mailhog, minio

make check        # what CI runs: ruff check + ruff format --check + mypy --strict + pytest
make lint | fmt | type | security          # individual gates (security = bandit + pip-audit)
```

Tests:

- `make test` runs with `--no-deps`, so **integration tests skip** when no database is reachable. To run the full suite, use `docker compose run --rm api pytest -q`, which starts db and redis first.
- Run a single test with: `docker compose run --rm api pytest -q tests/api/test_identity_api.py::test_name`

Scheme knowledge base: edit `config/knowledge/schemes.yml`, then run `docker compose run --rm api python -m app.console seed-knowledge`. It is idempotent and upserts by slug. The starter entries are **unverified** (`last_verified_on: null`), so check each against its `official_url`. The assistant may only answer from this data.

Ports on this machine (set in `.env`, because other projects hold the defaults): API 8000, MySQL 3308, Redis 6381, MinIO 9010/9011. Tests use their own database, `xuanwu_test`, and Redis DB 15. `tests/conftest.py` repoints settings before the app imports and migrates the test DB to head once per run. The DB is created by `docker/mysql-init/` on a fresh volume, or by the conftest if `rv` has the rights. It is never reset, so use random identifiers in tests and delete any `Scheme` rows a test creates.

Migrations: after changing a model, run `docker compose run --rm api alembic revision --autogenerate -m "..."`, review the file in `alembic/versions/`, then upgrade.

Dependencies: edit `pyproject.toml`, then run `make lock && make build`. `requirements.lock` holds the exact pins.

## Architecture

**Request path.** `app/main.py` builds the app with CORS, slowapi rate limiting (Redis-backed), and security headers. `public_router` is mounted outside the guarded tree so `/health` keeps working in maintenance mode. `app/api/v2/router.py` mounts everything else under `/api/v2/xuanwu/{identity,resource,admin}` with a `restriction_guard` dependency (IP/geo blacklist, maintenance mode, block-login) that runs on every request.

**Layering (keep it this way).** Routers in `app/api/v2/*` only validate input and serialize output. Logic lives in `app/services/*`, which take an `AsyncSession` and call `db.commit()` themselves. ORM rows never leave a handler raw: wrap them as `Envelope[XOut](data=XOut.model_validate(row))` using the schemas in `app/schemas/`.

**Responses and errors.** Success uses `{"success": true, "data": ...}`. Errors use `{"success": false, "errors": ["dotted.i18n.key"]}`. Raise `APIError(keys, status)` or the helpers `bad_request` / `unauthorized` / `forbidden` / `not_found` / `unprocessable` from `app/core/errors.py`. Never leak exception text.

**Auth dependencies** (`app/api/deps.py`):
- `current_user` reads the RS256 access JWT from an httpOnly cookie, or from a Bearer header for tooling.
- `authorized_user` adds the CSRF check on unsafe methods (`X-CSRF-Token` must match the `csrf_token` cookie), accepts API-key HMAC auth as an alternative, and runs the RBAC check.
- `admin_user`, `require_superadmin` and `superadmin_authorized` are the role-gated variants.
- Refresh-token `jti`s are tracked in Redis so sessions can be revoked.

**RBAC** (`app/core/authorize.py`). `config/authz_rules.yml` (pass/block path prefixes) is checked first. After that, the `permissions` table (role × verb × path prefix → ACCEPT/DROP/AUDIT) decides, with per-role results cached in Redis for 5 minutes. New routes need matching permission rows. Add them to `app/db/seeds.py` so `make seed` and the test fixtures pick them up.

**Levels and labels.** Verifying email, phone, or documents adds labels. Labels raise `User.level` (0–3) and drive account state (`level_service`).

**Audit.** Call `log_activity(...)` from `app/core/activity.py`. It enqueues a Celery task (`app/workers/activity.py`). Activity rows are append-only, enforced by a guard in the model. The spec's audit-log requirement should build on this.

**Integrations** (`app/integrations/{email,sms,storage}`). Each has a `base.py` interface, concrete providers, and a `get_provider()` that picks one from settings, with `mock` as the default. Follow this pattern for new STT/LLM services.

**Citizen login (prototype).** `POST /identity/sessions/mobile` takes `{mobile, otp, language}`. The OTP is `settings.prototype_otp` (`1111`). The first login creates a `citizen` user and an empty `CitizenProfile`. It sets the same auth cookies as email login and is refused when `APP_ENV=production`.

**Citizen profile** (`citizen_profile_service`, `GET /resource/citizen-profile/me`, `PATCH /resource/citizen-profile`, `GET /resource/districts`):
- Name and `preferred_language` live on `users`. Age (stored as `birth_year`), gender, marital status, district, `area_type` (rural/urban) and village live on `citizen_profiles`.
- `is_complete` (name, age, gender, marital status) is returned by mobile login as `profile_complete`. The frontend uses it to send new citizens to `/welcome`.
- The assistant's profile context renames `area_type` to `area`, so it matches the eligibility condition field.
- Audit entries record changed field names only, never the personal values.
- Districts are loaded from `config/knowledge/punjab.yml` by `seed-knowledge`.

**Assistant** (`app/services/assistant_service.py`, `POST /resource/conversations/messages`). Each turn:
1. Saves the citizen message.
2. Sends the citizen profile, conversation facts, **all active schemes** (full injection) and recent history to the LLM, with a JSON response schema.
3. Validates the answer against the database: unknown scheme slugs are dropped, and official name and URL always come from the DB.
4. Saves the assistant message (structured answer in `payload`), `message_schemes` and, when `answer_status=not_in_data`, an `UnansweredQuestion`.

LLM providers live in `app/integrations/llm/` (`LLM_PROVIDER=gemini|mock`, `GEMINI_API_KEY`, `LLM_MODEL`). `LLM_FALLBACK_MODEL` (default `gemini-3.5-flash-lite`) is tried once when the main model returns 429, 500 or 503; Gemini returns 503 "high demand" fairly often. Keep `LLM_THINKING_LEVEL=low`: Gemini 3's default "thinking" spends roughly 10× the output tokens. Tests force the mock provider; queue replies with `app.integrations.llm.mock.queue_response`. Reply language is enforced twice, in the system prompt and in a reminder on the last user message, because the model otherwise copies English scheme text into Punjabi answers.

**Voice messages** (`voice_service`, `POST /resource/conversations/transcriptions`, multipart `audio` + `language` + `duration_ms`):
- Speech-to-text sits behind `app/integrations/stt/` (`STT_PROVIDER=gemini|mock`). Gemini receives the clip inline and reuses the LLM's key, retry and fallback code (`call_gemini` in `llm/gemini.py`). WebM (Chrome), Ogg (Firefox) and MP4 (Safari) all work.
- Transcription never sends anything to the assistant. It stores the clip and returns the text plus a signed `voice_token`: a JWT with an HMAC key derived from `SECRET_KEY`, bound to the user, valid for `STT_TOKEN_TTL`.
- The client sends the text (edited or not) to `/conversations/messages` with the token. The message stores `original_transcript`, `transcript_corrected`, `audio_storage_key` and `audio_duration_ms`, and is marked `source=voice`.
- Rate limit: `RATE_LIMIT_VOICE` per IP. Tests force the mock; queue text with `app.integrations.stt.mock.queue_transcript`.
- Spoken replies: `POST /resource/conversations/messages/{id}/speech` returns WAV (not JSON) for the caller's own assistant messages. `app/integrations/tts/` (`TTS_PROVIDER=gemini|mock`, `TTS_MODEL` lite with `TTS_FALLBACK_MODEL`, `TTS_VOICE`). Links and markdown are stripped and long replies cut at a sentence end (`voice_service.speakable`). Rate limit `RATE_LIMIT_SPEECH`.
- The frontend's hands-free mode (mic button) auto-sends each transcript, with no review step; the complaint review screen is the check. It plays the reply, then listens again.
- Live words: WebSocket `/resource/conversations/live-transcription` (`app/services/live_voice.py`, protocol in its docstring) relays 16 kHz PCM to the Gemini Live transcription model (`STT_LIVE_MODEL`) and streams partial text back. It ends with the same signed `voice_token` as the upload path. Auth is the cookie plus an Origin check against `CORS_ORIGINS`, with a per-user Redis rate limit. Next.js can't forward WebSockets, so the browser connects to the API directly (`NEXT_PUBLIC_VOICE_WS_URL` locally, an nginx location on staging). If it isn't reachable, the client uploads the recording instead.
- Gemini ignores `maxLength`. When a reply is cut off by the token cap, `gemini._salvage` keeps the complete fields; the schema's `propertyOrdering` keeps the grievance draft last for this reason.

**Officer and administrator desk** (`staff_service`, `/resource/staff/*`):
- `GET /staff/me`, `GET /staff/grievances` (queue; `status` also takes `open` and `overdue`), `GET /staff/grievances/{ref}` (with transcript, history, notes, allowed `next_statuses`), `POST .../status`, `POST .../notes`, `GET /staff/overview?days=` (administrators only).
- Jurisdiction comes from `StaffProfile` (tehsil/district/state/system, optional department) and is applied to every query by `staff_service.Scope`. Superadmin sees everything. A grievance outside the caller's scope answers 404. Citizens get 403.
- Status moves are listed in `staff_service.TRANSITIONS`. Resolve, close and reopen need a remark, which the citizen sees. An officer's first action on an unassigned grievance assigns it to them.
- Demo staff accounts come from `config/knowledge/demo_staff.yml` (`python -m app.console seed-demo-staff`, run by the root `migrate` service; skipped in production). They log in on the normal mobile + OTP screen.

**Data.** SQLAlchemy 2.0 async (asyncmy) for the app. `app/db/sync_session.py` serves Celery workers. Sensitive columns use `EncryptedString` (`app/core/encryption.py`). Lookups on encrypted values use blind indexes (`app/utils/blind_index.py`). Public user IDs are `uid` strings (`app/utils/uid.py`), not the UUID primary key.

**Config.** `app/core/config.py` holds pydantic-settings loaded from `.env`; `.env.example` documents every variable. `settings.is_production` hides dev-only response fields such as returned verification codes.

## Testing conventions

- Tests mirror the app layout under `tests/{models,core,services,workers,api}/`.
- `tests/conftest.py` provides a per-test DB engine, `fakeredis`, eager Celery, and autouse mocks for email, SMS, storage, captcha and GeoIP. Its `db`, `client`, `make_user` and `login_as` fixtures are built on `tests/factories.py`.
- mypy runs in **strict** mode over both `app` and `tests`, so test code needs full type annotations.
- Ruff line length is 100.
- Security-critical code (auth, tokens, encryption, RBAC) needs direct test coverage.
