import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from tests.utils.notification import create_notification
from tests.utils.tokens import auth_headers, make_token

URL = f"{settings.API_V1_STR}/notifications"
RUNNER = uuid.UUID("00000000-0000-4000-8000-000000000001")
PAST = datetime(2020, 1, 1, tzinfo=UTC)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


REJECTED_CREDENTIALS: dict[str, Callable[[], dict[str, str]]] = {
    "no header": lambda: {},
    "empty bearer": lambda: {"Authorization": "Bearer "},
    "scheme only": lambda: {"Authorization": "Bearer"},
    "wrong scheme": lambda: {"Authorization": f"Basic {make_token(RUNNER)}"},
    "token without scheme": lambda: {"Authorization": make_token(RUNNER)},
    "garbage": lambda: bearer("not-a-jwt"),
    "expired": lambda: bearer(make_token(RUNNER, exp=PAST)),
    "no expiry": lambda: bearer(make_token(RUNNER, exp=None)),
    "wrong issuer": lambda: bearer(make_token(RUNNER, iss="someone-else")),
    "no issuer": lambda: bearer(make_token(RUNNER, iss=None)),
    "wrong audience": lambda: bearer(make_token(RUNNER, aud="another-service")),
    "refresh token audience": lambda: bearer(
        make_token(RUNNER, aud=f"{settings.JWT_AUDIENCE}-refresh")
    ),
    "no audience": lambda: bearer(make_token(RUNNER, aud=None)),
    "no subject": lambda: bearer(make_token(RUNNER, sub=None)),
    "subject not a uuid": lambda: bearer(make_token(RUNNER, sub="runner-1")),
    "wrong key": lambda: bearer(
        make_token(RUNNER, key="another-secret-that-is-longer-than-32-bytes")
    ),
    "wrong algorithm": lambda: bearer(make_token(RUNNER, algorithm="HS512")),
    "unsigned": lambda: bearer(make_token(RUNNER, key=None, algorithm="none")),
}


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", URL), ("PATCH", f"{URL}/{uuid.uuid4()}/read")],
    ids=["list", "read"],
)
@pytest.mark.parametrize(
    "credentials", REJECTED_CREDENTIALS.values(), ids=REJECTED_CREDENTIALS.keys()
)
def test_rejected_credentials_get_401(
    client: TestClient,
    method: str,
    path: str,
    credentials: Callable[[], dict[str, str]],
) -> None:
    response = client.request(method, path, headers=credentials())
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {
        "code": "UNAUTHORIZED",
        "message": "Could not validate credentials",
    }


def test_token_with_identitys_extra_claims_is_accepted(client: TestClient) -> None:
    token = make_token(
        RUNNER, id=str(RUNNER), email="ray@example.com", phoneVerified=True
    )
    assert client.get(URL, headers=bearer(token)).status_code == 200


def test_uppercase_bearer_scheme_is_accepted(client: TestClient) -> None:
    headers = {"Authorization": f"BEARER {make_token(RUNNER)}"}
    assert client.get(URL, headers=headers).status_code == 200


def test_invalid_input_without_token_gets_401_not_422(client: TestClient) -> None:
    assert client.patch(f"{URL}/not-a-uuid/read").status_code == 401
    assert client.get(URL, params={"limit": 0}).status_code == 401


def test_empty_inbox(client: TestClient) -> None:
    response = client.get(URL, headers=auth_headers(uuid.uuid4()))
    assert response.status_code == 200
    assert response.json() == {"items": [], "unreadCount": 0, "nextCursor": None}


def test_list_returns_the_public_shape(client: TestClient, db: Session) -> None:
    runner = uuid.uuid4()
    stored = create_notification(db, runner)
    body = client.get(URL, headers=auth_headers(runner)).json()
    assert list(body) == ["items", "unreadCount", "nextCursor"]
    item = body["items"][0]
    assert set(item) == {"id", "type", "category", "data", "occurredAt", "readAt"}
    assert item["id"] == str(stored.id)
    assert item["type"] == "BuddyRequestSent"
    assert item["category"] == "buddy_requests"
    assert item["data"] == stored.payload
    assert item["readAt"] is None
    assert datetime.fromisoformat(item["occurredAt"]) == stored.occurred_at
    assert datetime.fromisoformat(item["occurredAt"]).tzinfo is not None


def test_list_only_returns_the_callers_notifications(
    client: TestClient, db: Session
) -> None:
    runner, other = uuid.uuid4(), uuid.uuid4()
    mine = create_notification(db, runner)
    create_notification(db, other)
    body = client.get(URL, headers=auth_headers(runner)).json()
    assert [item["id"] for item in body["items"]] == [str(mine.id)]
    assert body["unreadCount"] == 1


def test_list_is_newest_first(client: TestClient, db: Session) -> None:
    runner = uuid.uuid4()
    oldest = create_notification(db, runner, occurred_at=PAST)
    newest = create_notification(db, runner, occurred_at=PAST + timedelta(hours=2))
    middle = create_notification(db, runner, occurred_at=PAST + timedelta(hours=1))
    body = client.get(URL, headers=auth_headers(runner)).json()
    assert [item["id"] for item in body["items"]] == [
        str(newest.id),
        str(middle.id),
        str(oldest.id),
    ]


def test_pages_cover_every_notification_once_even_with_equal_times(
    client: TestClient, db: Session
) -> None:
    runner = uuid.uuid4()
    expected = {
        str(create_notification(db, runner, occurred_at=PAST).id) for _ in range(5)
    }
    seen: list[str] = []
    cursor = None
    for _ in range(3):
        params = {"limit": 2} | ({"before": cursor} if cursor else {})
        body = client.get(URL, headers=auth_headers(runner), params=params).json()
        seen += [item["id"] for item in body["items"]]
        cursor = body["nextCursor"]
    assert len(seen) == 5
    assert set(seen) == expected
    assert cursor is None


def test_exact_final_page_has_no_cursor(client: TestClient, db: Session) -> None:
    runner = uuid.uuid4()
    for _ in range(2):
        create_notification(db, runner)
    body = client.get(URL, headers=auth_headers(runner), params={"limit": 2}).json()
    assert len(body["items"]) == 2
    assert body["nextCursor"] is None


def test_unread_count_covers_the_whole_inbox_not_the_page(
    client: TestClient, db: Session
) -> None:
    runner = uuid.uuid4()
    for _ in range(3):
        create_notification(db, runner)
    create_notification(db, runner, read_at=PAST)
    body = client.get(URL, headers=auth_headers(runner), params={"limit": 1}).json()
    assert len(body["items"]) == 1
    assert body["unreadCount"] == 3


def test_cursor_from_another_runner_reveals_nothing(
    client: TestClient, db: Session
) -> None:
    runner = uuid.uuid4()
    create_notification(db, runner)
    theirs = create_notification(db, uuid.uuid4())
    body = client.get(
        URL, headers=auth_headers(runner), params={"before": str(theirs.id)}
    ).json()
    assert body["items"] == []
    assert body["nextCursor"] is None


@pytest.mark.parametrize(
    "params",
    [{"limit": 0}, {"limit": 101}, {"limit": "many"}, {"before": "not-a-uuid"}],
    ids=["limit too low", "limit too high", "limit not a number", "bad cursor"],
)
def test_invalid_query_gets_fastapis_native_422(
    client: TestClient, params: dict[str, str | int]
) -> None:
    response = client.get(URL, headers=auth_headers(RUNNER), params=params)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_read_marks_the_notification_and_lowers_the_unread_count(
    client: TestClient, db: Session
) -> None:
    runner = uuid.uuid4()
    stored = create_notification(db, runner)
    create_notification(db, runner)
    response = client.patch(f"{URL}/{stored.id}/read", headers=auth_headers(runner))
    assert response.status_code == 200
    assert response.json()["id"] == str(stored.id)
    assert response.json()["readAt"] is not None
    body = client.get(URL, headers=auth_headers(runner)).json()
    assert body["unreadCount"] == 1


def test_reading_twice_keeps_the_first_time(client: TestClient, db: Session) -> None:
    runner = uuid.uuid4()
    stored = create_notification(db, runner)
    first = client.patch(f"{URL}/{stored.id}/read", headers=auth_headers(runner))
    second = client.patch(f"{URL}/{stored.id}/read", headers=auth_headers(runner))
    assert second.status_code == 200
    assert second.json()["readAt"] == first.json()["readAt"]


def test_another_runners_notification_looks_missing_and_stays_unread(
    client: TestClient, db: Session
) -> None:
    owner, intruder = uuid.uuid4(), uuid.uuid4()
    stored = create_notification(db, owner)
    theirs = client.patch(f"{URL}/{stored.id}/read", headers=auth_headers(intruder))
    missing = client.patch(f"{URL}/{uuid.uuid4()}/read", headers=auth_headers(intruder))
    assert theirs.status_code == 404
    assert theirs.json() == missing.json()
    assert theirs.json()["code"] == "NOT_FOUND"
    db.refresh(stored)
    assert stored.read_at is None


def test_invalid_notification_id_gets_422_with_a_token(client: TestClient) -> None:
    response = client.patch(f"{URL}/not-a-uuid/read", headers=auth_headers(RUNNER))
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


@pytest.mark.usefixtures("database_down")
@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", URL), ("PATCH", f"{URL}/{uuid.uuid4()}/read")],
    ids=["list", "read"],
)
def test_database_outage_gets_503_without_leaking_details(
    client: TestClient, method: str, path: str
) -> None:
    response = client.request(method, path, headers=auth_headers(RUNNER))
    assert response.status_code == 503
    assert response.json() == {
        "code": "SERVICE_UNAVAILABLE",
        "message": "Notifications are unavailable right now",
    }


@pytest.mark.usefixtures("database_down")
def test_outage_does_not_affect_health_or_token_checks(client: TestClient) -> None:
    assert client.get("/up").status_code == 200
    assert client.get(URL).status_code == 401


def test_unknown_route_uses_the_error_shape(client: TestClient) -> None:
    response = client.get("/api/v1/nothing-here")
    assert response.status_code == 404
    assert set(response.json()) == {"code", "message"}
    assert response.json()["code"] == "NOT_FOUND"
