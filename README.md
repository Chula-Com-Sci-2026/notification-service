# Notification Service

In-app notifications for Can't Run Alone, built on a FastAPI service template.

**Status:** the inbox API works, but nothing creates notifications yet because the RabbitMQ consumer is not built.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/up` | Liveness, no token needed |
| `GET` | `/api/v1/notifications` | The caller's inbox, newest first. Optional `limit` (1-100, default 50) and `before` (a `nextCursor` value) |
| `PATCH` | `/api/v1/notifications/{id}/read` | Mark as read. Repeat calls keep the first time |

Every `/api/v1` call needs an `Authorization: Bearer <token>` header carrying an Identity access token. A bad token gets 401, and another runner's notification ID gets the same 404 as a missing one.

Errors use `{"code", "message"}`, except FastAPI's native 422.

## Contracts

The interfaces this service must honor live in [running-buddy-contracts](https://github.com/Chula-Com-Sci-2026/running-buddy-contracts): `notification.openapi.json`, `events.md` and `buddy-events.schema.json`. `tests/contracts/` holds a copy that the tests check the service against.

Design decisions are in [running-buddy-ADRs](https://github.com/Chula-Com-Sci-2026/running-buddy-ADRs), mainly ADR-0020, ADR-0021 and ADR-0022.

This service runs Python 3.14 because the template requires it, while ADR-0020 names 3.13. Compatibility depends on the contracts, not the Python version.

## Run

```bash
cp .env.example .env
docker compose up --build --wait
curl http://127.0.0.1:8010/up
```

The API docs are at <http://127.0.0.1:8010/docs> and the RabbitMQ console is at <http://127.0.0.1:15673>. All ports bind to loopback.

To accept real tokens, set `ACCESS_TOKEN_SECRET`, `JWT_ISSUER` and `JWT_AUDIENCE` in `.env` to Identity's values. The service refuses to start without `ACCESS_TOKEN_SECRET`.

## Develop

Tests need the Compose database running. They create and drop their own `notification_test` database, so they never touch your local data.

```bash
docker compose up --wait db
uv sync
uv run bash scripts/test.sh
uv run bash scripts/lint.sh
```

After changing `app/models.py`, write a migration and read it before committing:

```bash
uv run alembic revision --autogenerate -m "Describe the change"
uv run alembic upgrade head
```
