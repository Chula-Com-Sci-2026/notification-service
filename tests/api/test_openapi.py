import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from sqlmodel import Session

from tests.utils.notification import create_notification
from tests.utils.tokens import auth_headers

# Copied from running-buddy-contracts, so the suite runs without a sibling checkout.
CONTRACT: dict[str, Any] = json.loads(
    (Path(__file__).parents[1] / "contracts" / "notification.openapi.json").read_text()
)
LIST = "/api/v1/notifications"
READ = "/api/v1/notifications/{notification_id}/read"


def assert_documented(
    response: httpx2.Response, path: str, method: str, status: int
) -> None:
    """Check a response has the expected status and fits the contract's schema.

    Args:
        response (httpx2.Response): The response to check.
        path (str): The contract's path template.
        method (str): The contract's lowercase HTTP method.
        status (int): The expected status, which the contract must document.
    """
    assert response.status_code == status
    documented = CONTRACT["paths"][path][method]["responses"][str(status)]
    schema = documented["content"]["application/json"]["schema"]
    Draft202012Validator(
        schema | {"components": CONTRACT["components"]},
        format_checker=FormatChecker(),
    ).validate(response.json())


def test_served_api_is_exactly_the_contract(client: TestClient) -> None:
    """Fail on any API change until the contract is exported again."""
    assert client.get("/openapi.json").json() == CONTRACT


def test_health_response_fits_the_contract(client: TestClient) -> None:
    assert_documented(client.get("/up"), "/up", "get", 200)


def test_list_responses_fit_the_contract(client: TestClient, db: Session) -> None:
    runner = uuid.uuid4()
    create_notification(db, runner)
    create_notification(db, runner, read_at=datetime.now(UTC))
    headers = auth_headers(runner)
    page = client.get(LIST, headers=headers, params={"limit": 1})
    assert_documented(page, LIST, "get", 200)
    assert page.json()["nextCursor"] is not None
    last = client.get(LIST, headers=headers)
    assert_documented(last, LIST, "get", 200)
    assert last.json()["nextCursor"] is None
    assert_documented(client.get(LIST), LIST, "get", 401)
    invalid = client.get(LIST, headers=headers, params={"limit": 0})
    assert_documented(invalid, LIST, "get", 422)


def test_read_responses_fit_the_contract(client: TestClient, db: Session) -> None:
    runner = uuid.uuid4()
    url = f"{LIST}/{create_notification(db, runner).id}/read"
    headers = auth_headers(runner)
    assert_documented(client.patch(url, headers=headers), READ, "patch", 200)
    assert_documented(client.patch(url), READ, "patch", 401)
    missing = client.patch(f"{LIST}/{uuid.uuid4()}/read", headers=headers)
    assert_documented(missing, READ, "patch", 404)
    invalid = client.patch(f"{LIST}/not-a-uuid/read", headers=headers)
    assert_documented(invalid, READ, "patch", 422)


@pytest.mark.usefixtures("database_down")
def test_outage_responses_fit_the_contract(client: TestClient) -> None:
    headers = auth_headers(uuid.uuid4())
    assert_documented(client.get(LIST, headers=headers), LIST, "get", 503)
    url = f"{LIST}/{uuid.uuid4()}/read"
    assert_documented(client.patch(url, headers=headers), READ, "patch", 503)
