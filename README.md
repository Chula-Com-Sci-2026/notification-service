# Notification Service

In-app notifications for Can't Run Alone, built on a FastAPI service template.

**Status:** buddy events become notifications, runners can read them, and runners can turn categories off. Run events are not built yet, so `buddy_requests` is the only category that receives anything today.

It runs as two processes from one image: `api` serves the inbox and `consumer` stores events. Either keeps working while the other's dependency is down.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/up` | Liveness, no token needed |
| `GET` | `/api/v1/notifications` | The caller's inbox, newest first. Optional `limit` (1-100, default 50) and `before` (a `nextCursor` value) |
| `PATCH` | `/api/v1/notifications/{id}/read` | Mark as read. Repeat calls keep the first time |
| `GET` | `/api/v1/notifications/preferences` | The caller's setting for every category |
| `PATCH` | `/api/v1/notifications/preferences` | Change some categories, for example `{"categories": {"reminders": false}}` |

Every `/api/v1` call needs an `Authorization: Bearer <token>` header carrying an Identity access token. A bad token gets 401, and another runner's notification ID gets the same 404 as a missing one.

Errors use `{"code", "message"}`, except FastAPI's native 422.

## Preferences

The categories are `buddy_requests`, `run_invitations`, `run_changes`, `reminders`, `weather_alerts` and `attendance_prompts`. Every category starts on. `run_changes` is locked on (FR-9.2), so turning it off gets a 422.

An event in a category that is off is acknowledged and not stored. Turning the category back on applies to later events only, and turning it off leaves existing notifications in the inbox.

## Publishing events

The consumer takes the buddy events in `events.md` and targets `recipientId` for `BuddyRequestSent` and `senderId` for `BuddyRequestAnswered`.

| Item | Value |
| --- | --- |
| Exchange | `cra.events`, durable topic |
| Routing key | The event's `eventType`, which must match or the event is dead-lettered |
| Message | Persistent JSON, `buddy-events.schema.json` |
| Queue | `notifications.events`, durable, dead-letters to `cra.dead` |
| Dead letters | `cra.dead`, durable topic, into `notifications.dead` |

The consumer declares all of this when it starts, so it has to have run once before anything can publish. Until then the exchange does not exist, and until its queue is bound an event comes back unrouted and should stay in the publisher's outbox.

Delivery is at least once. A redelivered `eventId` is ignored, an invalid message goes to `notifications.dead`, and a database failure requeues the event and retries after a 3 second delay, so it is never lost.

## Correlation IDs

Every log line has `correlation_id=<uuid>`. The consumer uses the event's `correlationId`. The API uses the `X-Correlation-Id` request header, or creates one if it is missing or not a UUID, and returns it on the response. A gateway should forward this header along with `Authorization`.

## Contracts

The interfaces this service must honor live in [running-buddy-contracts](https://github.com/Chula-Com-Sci-2026/running-buddy-contracts): `notification.openapi.json`, `events.md` and `buddy-events.schema.json`. `tests/contracts/` holds copies that the tests check the service against.

The served API must exactly match `tests/contracts/notification.openapi.json`, so any API change fails the tests until you save the running service's `http://127.0.0.1:8010/openapi.json` over that file. Send the same change to the contracts repo.

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

Tests need the Compose database and broker running. They create their own `notification_test` database and vhost, so they never touch your local data or a running consumer.

```bash
docker compose up --wait db rabbitmq
uv sync
uv run bash scripts/test.sh
uv run bash scripts/lint.sh
```

After changing `app/models.py`, write a migration and read it before committing:

```bash
uv run alembic revision --autogenerate -m "Describe the change"
uv run alembic upgrade head
```
