# Notification Service

In-app notifications for Can't Run Alone, built on a FastAPI service template.

**Status:** health endpoint and database schema only. The inbox API and the RabbitMQ consumer are not built yet.

## Contracts

The interfaces this service must honor live in [running-buddy-contracts](https://github.com/Chula-Com-Sci-2026/running-buddy-contracts): `notification.openapi.json`, `events.md` and `buddy-events.schema.json`.

Design decisions are in [running-buddy-ADRs](https://github.com/Chula-Com-Sci-2026/running-buddy-ADRs), mainly ADR-0020, ADR-0021 and ADR-0022.

This service runs Python 3.14 because the template requires it, while ADR-0020 names 3.13. Compatibility depends on the contracts, not the Python version.

## Run

```bash
cp .env.example .env
docker compose up --build --wait
curl http://127.0.0.1:8010/up
```

The API docs are at <http://127.0.0.1:8010/docs> and the RabbitMQ console is at <http://127.0.0.1:15673>. All ports bind to loopback.

## Develop

Keep the Compose stack running for the database. Tests read `.env`.

```bash
uv sync
uv run bash scripts/test.sh
uv run bash scripts/lint.sh
```

After changing `app/models.py`, write a migration and read it before committing:

```bash
uv run alembic revision --autogenerate -m "Describe the change"
uv run alembic upgrade head
```
