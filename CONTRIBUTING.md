# Contributing to Xuanwu

Thanks for your interest in improving Xuanwu. This guide covers the workflow and
the quality bar every change must clear.

## Ground rules

- **Everything runs in Docker.** No local Python is required or expected — the
  image carries the interpreter, dependencies, and tooling. Run commands through
  `docker compose` or the `make` wrappers.
- **One concern per pull request.** Keep diffs reviewable.
- **Match the surrounding code.** Services hold the logic, routers only validate
  and serialize, ORM rows never leave a handler un-wrapped by a Pydantic `*Out`
  schema. See `docs` for the full conventions.

## Getting set up

```bash
git clone https://github.com/sudhanshu-17/xuanwu.git
cd xuanwu
cp .env.example .env
make build
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m app.console seed
make up                       # http://localhost:8000/health
```

## Before you open a PR

All gates must be green. They are exactly what CI runs:

```bash
make check       # ruff (lint) + ruff format --check + mypy --strict + pytest
make security    # bandit + pip-audit
```

If you changed dependencies, regenerate the lockfile and rebuild:

```bash
make lock
make build
```

If you changed a model, generate and review a migration:

```bash
docker compose run --rm api alembic revision --autogenerate -m "describe change"
# review the file under alembic/versions/, then:
docker compose run --rm api alembic upgrade head
```

## Tests

- Add tests under `tests/{models,core,services,workers,api}/` mirroring the code.
- Integration tests use a per-test database + fakeredis; external services
  (email, SMS, storage, captcha, GeoIP) are mocked by autouse fixtures.
- New security-critical code (auth, tokens, encryption, RBAC) needs direct
  coverage, not just incidental.

## Commit messages

Write clear, imperative, human commit messages describing the change and why.

## Reporting security issues

Please do not open public issues for vulnerabilities. Email the maintainers
privately so a fix can ship before disclosure.
