import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app.core.config import settings
from app.models import CATEGORIES, NotificationPreference
from tests.utils.notification import create_notification
from tests.utils.tokens import auth_headers

URL = f"{settings.API_V1_STR}/notifications/preferences"
INBOX = f"{settings.API_V1_STR}/notifications"


def settings_of(client: TestClient, runner: uuid.UUID) -> dict[str, bool]:
    body = client.get(URL, headers=auth_headers(runner)).json()
    return {item["category"]: item["enabled"] for item in body["items"]}


def change(client: TestClient, runner: uuid.UUID, **categories: bool) -> Any:
    return client.patch(
        URL, headers=auth_headers(runner), json={"categories": categories}
    )


def stored_rows(db: Session, runner: uuid.UUID) -> list[NotificationPreference]:
    return list(
        db.exec(
            select(NotificationPreference).where(
                NotificationPreference.recipient_id == runner
            )
        ).all()
    )


def test_a_new_runner_has_everything_on_and_only_run_changes_locked(
    client: TestClient,
) -> None:
    response = client.get(URL, headers=auth_headers(uuid.uuid4()))
    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {"category": "buddy_requests", "enabled": True, "locked": False},
            {"category": "run_invitations", "enabled": True, "locked": False},
            {"category": "run_changes", "enabled": True, "locked": True},
            {"category": "reminders", "enabled": True, "locked": False},
            {"category": "weather_alerts", "enabled": True, "locked": False},
            {"category": "attendance_prompts", "enabled": True, "locked": False},
        ]
    }


def test_turning_a_category_off_is_saved_and_leaves_the_others_on(
    client: TestClient,
) -> None:
    runner = uuid.uuid4()
    response = change(client, runner, buddy_requests=False)
    assert response.status_code == 200
    assert {i["category"]: i["enabled"] for i in response.json()["items"]} == (
        settings_of(client, runner)
    )
    expected = dict.fromkeys(CATEGORIES, True) | {"buddy_requests": False}
    assert settings_of(client, runner) == expected


def test_a_category_can_be_turned_back_on(client: TestClient) -> None:
    runner = uuid.uuid4()
    change(client, runner, reminders=False)
    change(client, runner, reminders=True)
    assert settings_of(client, runner)["reminders"] is True


def test_repeating_a_change_is_harmless(client: TestClient) -> None:
    runner = uuid.uuid4()
    for _ in range(2):
        assert change(client, runner, reminders=False).status_code == 200
    assert settings_of(client, runner)["reminders"] is False


def test_several_categories_can_change_at_once(client: TestClient) -> None:
    runner = uuid.uuid4()
    change(client, runner, reminders=False, weather_alerts=False)
    current = settings_of(client, runner)
    assert (current["reminders"], current["weather_alerts"]) == (False, False)
    assert current["buddy_requests"] is True


def test_one_runners_settings_do_not_affect_another(client: TestClient) -> None:
    runner, other = uuid.uuid4(), uuid.uuid4()
    change(client, runner, buddy_requests=False)
    assert settings_of(client, other)["buddy_requests"] is True


def test_run_changes_cannot_be_turned_off(client: TestClient, db: Session) -> None:
    runner = uuid.uuid4()
    response = change(client, runner, run_changes=False)
    assert response.status_code == 422
    assert "run_changes cannot be turned off" in response.json()["detail"][0]["msg"]
    assert settings_of(client, runner)["run_changes"] is True
    assert stored_rows(db, runner) == []


def test_a_rejected_request_changes_nothing_at_all(
    client: TestClient, db: Session
) -> None:
    runner = uuid.uuid4()
    response = change(client, runner, reminders=False, run_changes=False)
    assert response.status_code == 422
    assert settings_of(client, runner)["reminders"] is True
    assert stored_rows(db, runner) == []


def test_turning_run_changes_on_succeeds_and_stores_nothing(
    client: TestClient, db: Session
) -> None:
    runner = uuid.uuid4()
    assert change(client, runner, run_changes=True).status_code == 200
    assert stored_rows(db, runner) == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"categories": {}},
        {"categories": {"newsletters": False}},
        {"categories": {"reminders": "false"}},
        {"categories": {"reminders": 0}},
        {"categories": {"reminders": None}},
        {"categories": "reminders"},
        {"buddy_requests": False},
    ],
    ids=[
        "no categories",
        "empty categories",
        "unknown category",
        "text value",
        "number value",
        "null value",
        "not an object",
        "flat body",
    ],
)
def test_invalid_body_gets_fastapis_native_422(
    client: TestClient, body: dict[str, Any]
) -> None:
    runner = uuid.uuid4()
    response = client.patch(URL, headers=auth_headers(runner), json=body)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert all(settings_of(client, runner).values())


def test_invalid_body_without_a_token_gets_401_not_422(client: TestClient) -> None:
    assert client.patch(URL, json={}).status_code == 401


def test_malformed_json_without_a_token_is_rejected_and_changes_nothing(
    client: TestClient,
) -> None:
    response = client.patch(
        URL, content=b"{not json", headers={"Content-Type": "application/json"}
    )
    assert response.status_code in {401, 422}


def test_preferences_path_is_not_treated_as_a_notification_id(
    client: TestClient,
) -> None:
    runner = uuid.uuid4()
    assert client.get(URL, headers=auth_headers(runner)).status_code == 200
    response = client.patch(f"{URL}/read", headers=auth_headers(runner))
    assert response.status_code == 422


def test_turning_a_category_off_keeps_what_is_already_in_the_inbox(
    client: TestClient, db: Session
) -> None:
    runner = uuid.uuid4()
    create_notification(db, runner)
    change(client, runner, buddy_requests=False)
    body = client.get(INBOX, headers=auth_headers(runner)).json()
    assert len(body["items"]) == 1
