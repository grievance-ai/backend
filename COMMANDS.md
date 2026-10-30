# Commands Cheat Sheet

Everything runs through Docker — no local Python needed. Run all commands from
the `xuanwu/` directory.

> `docker compose run --rm api …` auto-starts **db + redis** first (they have
> healthchecks). Add `--no-deps` to skip that when they're already running
> (faster for lint/type/test that don't touch the database).

---

## First-time / setup

```bash
cp .env.example .env                                  # create local env (once)
docker compose run --rm api alembic upgrade head      # build the schema
docker compose run --rm api python -m app.console seed                            # RBAC permissions + levels (idempotent)
docker compose run --rm api python -m app.console create-superadmin --email admin@example.com  # bootstrap admin
```

> Equivalent `make` targets: `make migrate`, `make seed`,
> `make superadmin EMAIL=admin@example.com`.

## Operator console

```bash
docker compose run --rm api python -m app.console generate-keys          # write the RS256 JWT keypair
docker compose run --rm api python -m app.console generate-keys --force  # rotate (invalidates all tokens)
docker compose run --rm api python -m app.console seed                   # default permissions + levels
docker compose run --rm api python -m app.console create-superadmin --email admin@example.com [--username admin] [--password ...]
```

> `python -m app.db.seeds` still works as a thin alias for the seed command.

## Background workers (Celery)

```bash
docker compose up worker                   # process tasks (email, SMS, audit writes)
docker compose up beat                     # scheduler (daily expired-token sweep)
docker compose up                          # the whole stack at once
```

## Run the app

```bash
docker compose up api            # start API (+ db + redis) → http://localhost:8000
docker compose up -d api         # same, in the background
docker compose logs -f api       # follow logs (Ctrl-C to stop following)
docker compose ps                # what's running
docker compose down              # stop everything (keeps data volume)
docker compose down -v           # stop AND wipe the database volume
docker compose restart api       # restart just the API
```

Handy URLs:

| URL | What |
|---|---|
| http://localhost:8000/docs | Swagger UI (try endpoints here) |
| http://localhost:8000/health | liveness |
| http://localhost:8000/health/ready | db + redis connectivity |
| http://localhost:8000/api/v2/xuanwu/identity/ping | identity namespace |

## Migrations (Alembic)

```bash
# Apply everything (most common)
docker compose run --rm api alembic upgrade head

# --- check status ---
docker compose run --rm api alembic current -v     # where the DB is now
docker compose run --rm api alembic heads           # latest revision in code
docker compose run --rm api alembic history -v      # full history, DB marked
docker compose run --rm api alembic check           # models vs DB in sync?

# --- roll back ---
docker compose run --rm api alembic downgrade -1    # one step back
docker compose run --rm api alembic downgrade base  # drop everything

# --- create a new migration after changing models ---
docker compose run --rm api alembic revision --autogenerate -m "describe change"
# then review the file in alembic/versions/ and:
docker compose run --rm api alembic upgrade head
```

**In sync when:** `alembic current` == `alembic heads` (and `alembic check`
reports no new operations).

## Database & Redis access

```bash
# MySQL shell  (db: xuanwu, user: rv / rv)
docker compose exec db mysql -urv -prv xuanwu
docker compose exec db mysql -urv -prv xuanwu -e "SHOW TABLES;"
docker compose exec db mysql -urv -prv xuanwu -e "SELECT * FROM alembic_version;"

# Redis shell
docker compose exec redis redis-cli
```

Host ports (configurable in `.env`): API `8000`, MySQL `3307`, Redis `6380`.

## Quality gates (CI)

```bash
docker compose run --rm --no-deps api ruff check .          # lint
docker compose run --rm --no-deps api ruff format .         # auto-format
docker compose run --rm --no-deps api ruff format --check . # format check only
docker compose run --rm --no-deps api mypy                  # type check
docker compose run --rm api pytest -q                       # tests (needs db+redis)
docker compose run --rm --no-deps api bandit -q -c pyproject.toml -r app
docker compose run --rm --no-deps api pip-audit --ignore-vuln CVE-2025-65896
```

> Run `pytest` **with** db+redis (no `--no-deps`) so the integration tests run;
> otherwise they skip.

## Dependencies

```bash
# Regenerate the pinned lockfile after editing pyproject.toml, then rebuild
docker run --rm -v "$PWD":/w -w /w python:3.12-slim-bookworm \
  sh -c "pip install -q 'uv>=0.5,<0.6' && uv pip compile --upgrade pyproject.toml --extra dev -o requirements.lock"
docker compose build api
```

## Makefile shortcuts

```bash
make help        # list targets
make build       # build the image
make up          # start the API
make down        # stop everything
make check       # ruff + format + mypy + pytest
make security    # bandit + pip-audit
make lock        # regenerate requirements.lock
```
