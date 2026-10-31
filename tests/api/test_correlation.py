import logging
import uuid

import pytest
from fastapi.testclient import TestClient

from app.api.middleware import CORRELATION_HEADER
from app.core.config import settings
from tests.utils.tokens import auth_headers

URL = f"{settings.API_V1_STR}/notifications"


def test_callers_correlation_id_is_returned(client: TestClient) -> None:
    value = str(uuid.uuid4())
    response = client.get("/up", headers={CORRELATION_HEADER: value})
    assert response.headers[CORRELATION_HEADER] == value


def test_missing_correlation_id_gets_a_new_uuid(client: TestClient) -> None:
    first = client.get("/up").headers[CORRELATION_HEADER]
    second = client.get("/up").headers[CORRELATION_HEADER]
    assert str(uuid.UUID(first)) == first
    assert first != second


@pytest.mark.parametrize(
    "value",
    ["not-a-uuid", "abc correlation_id=forged", "x" * 500],
    ids=["text", "log forgery", "very long"],
)
def test_unusable_correlation_id_is_replaced(client: TestClient, value: str) -> None:
    returned = client.get("/up", headers={CORRELATION_HEADER: value}).headers[
        CORRELATION_HEADER
    ]
    assert returned != value
    assert str(uuid.UUID(returned)) == returned


def test_error_responses_carry_the_correlation_id(client: TestClient) -> None:
    value = str(uuid.uuid4())
    response = client.get(URL, headers={CORRELATION_HEADER: value})
    assert response.status_code == 401
    assert response.headers[CORRELATION_HEADER] == value


@pytest.mark.usefixtures("database_down")
def test_logs_during_a_request_name_its_correlation_id(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    value = str(uuid.uuid4())
    headers = auth_headers(uuid.uuid4()) | {CORRELATION_HEADER: value}
    with caplog.at_level(logging.ERROR, logger="app.main"):
        response = client.get(URL, headers=headers)
    assert response.status_code == 503
    assert response.headers[CORRELATION_HEADER] == value
    records = [r for r in caplog.records if r.name == "app.main"]
    assert [r.__dict__["correlation_id"] for r in records] == [value]
