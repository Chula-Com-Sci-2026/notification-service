import json
import logging
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from app.consumer import handle_delivery
from app.core.db import engine
from app.core.logs import correlation_id
from app.models import Notification
from tests.utils.events import make_event

TAG = 7


def deliver(body: bytes | dict[str, Any], routing_key: str | None = None) -> MagicMock:
    """Hand one message to the handler and return the channel it used."""
    channel = MagicMock()
    if isinstance(body, dict):
        routing_key = routing_key or body["eventType"]
        body = json.dumps(body).encode()
    method = SimpleNamespace(
        delivery_tag=TAG, routing_key=routing_key or "BuddyRequestSent"
    )
    handle_delivery(channel, method, None, body)
    return channel


def stored_for(runner: uuid.UUID) -> list[Notification]:
    with Session(engine) as session:
        return list(
            session.exec(
                select(Notification).where(Notification.recipient_id == runner)
            ).all()
        )


def test_row_is_already_committed_when_the_ack_is_sent() -> None:
    runner = uuid.uuid4()
    seen_at_ack: list[int] = []
    channel = MagicMock()
    channel.basic_ack.side_effect = lambda _tag: seen_at_ack.append(
        len(stored_for(runner))
    )
    event = make_event(recipient_id=runner)
    method = SimpleNamespace(delivery_tag=TAG, routing_key=event["eventType"])

    handle_delivery(channel, method, None, json.dumps(event).encode())

    assert seen_at_ack == [1]
    channel.basic_ack.assert_called_once_with(TAG)
    channel.basic_reject.assert_not_called()


def test_stored_row_holds_the_event() -> None:
    runner = uuid.uuid4()
    event = make_event(recipient_id=runner)
    event["payload"]["note"] = "not part of the contract"

    deliver(event)

    row = stored_for(runner)[0]
    assert str(row.event_id) == event["eventId"]
    assert row.event_type == "BuddyRequestSent"
    assert row.category == "buddy_requests"
    assert row.read_at is None
    assert row.occurred_at.tzinfo is not None
    assert row.payload == {
        "requestId": event["payload"]["requestId"],
        "senderId": event["payload"]["senderId"],
        "recipientId": str(runner),
        "status": "pending",
    }


def test_answered_event_is_stored_for_the_original_sender() -> None:
    sender, answerer = uuid.uuid4(), uuid.uuid4()
    deliver(make_event("BuddyRequestAnswered", sender_id=sender, recipient_id=answerer))
    assert len(stored_for(sender)) == 1
    assert stored_for(answerer) == []


def test_duplicate_delivery_is_acked_and_stored_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    runner = uuid.uuid4()
    event = make_event(recipient_id=runner)
    deliver(event)
    with caplog.at_level(logging.INFO, logger="app.consumer"):
        channel = deliver(event)
    channel.basic_ack.assert_called_once_with(TAG)
    assert len(stored_for(runner)) == 1
    assert f"Ignored duplicate event {event['eventId']}" in caplog.text


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"\xff\xfe",
        json.dumps(make_event(version=2)).encode(),
        json.dumps(make_event(status="accepted")).encode(),
        json.dumps(make_event(occurredAt=1793000000)).encode(),
    ],
    ids=["bad json", "bad bytes", "wrong version", "wrong status", "lax timestamp"],
)
def test_invalid_message_is_dead_lettered_not_requeued(body: bytes) -> None:
    channel = deliver(body)
    channel.basic_reject.assert_called_once_with(TAG, requeue=False)
    channel.basic_ack.assert_not_called()


def test_routing_key_must_match_the_event_type() -> None:
    runner = uuid.uuid4()
    event = make_event(recipient_id=runner)
    channel = deliver(event, routing_key="BuddyRequestAnswered")
    channel.basic_reject.assert_called_once_with(TAG, requeue=False)
    channel.basic_ack.assert_not_called()
    assert stored_for(runner) == []


def test_rejected_message_content_is_never_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    body = json.dumps({"eventId": "private-value", "otp": "123456"}).encode()
    with caplog.at_level(logging.WARNING, logger="app.consumer"):
        deliver(body)
    assert "Rejected invalid message" in caplog.text
    assert "private-value" not in caplog.text
    assert "123456" not in caplog.text


def test_database_failure_neither_acks_nor_rejects() -> None:
    channel = MagicMock()
    event = make_event()
    method = SimpleNamespace(delivery_tag=TAG, routing_key=event["eventType"])
    failure = OperationalError("INSERT", {}, Exception("database is down"))
    with (
        patch("app.consumer.crud.create_notification_from_event", side_effect=failure),
        pytest.raises(OperationalError),
    ):
        handle_delivery(channel, method, None, json.dumps(event).encode())
    channel.basic_ack.assert_not_called()
    channel.basic_reject.assert_not_called()


def test_database_failure_logs_one_line_without_sql_or_parameters(
    caplog: pytest.LogCaptureFixture,
) -> None:
    event = make_event()
    method = SimpleNamespace(delivery_tag=TAG, routing_key=event["eventType"])
    failure = OperationalError(
        "INSERT INTO notifications",
        {"p": "private-value"},
        Exception("server\nis down"),
    )
    with (
        caplog.at_level(logging.ERROR, logger="app.consumer"),
        patch("app.consumer.crud.create_notification_from_event", side_effect=failure),
        pytest.raises(OperationalError),
    ):
        handle_delivery(MagicMock(), method, None, json.dumps(event).encode())
    assert f"Could not store event {event['eventId']}: server is down" in caplog.text
    assert "INSERT" not in caplog.text
    assert "private-value" not in caplog.text


def test_logs_name_the_events_correlation_id_then_clear_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    event = make_event()
    with caplog.at_level(logging.INFO, logger="app.consumer"):
        deliver(event)
    records = [r for r in caplog.records if r.name == "app.consumer"]
    assert [r.__dict__["correlation_id"] for r in records] == [event["correlationId"]]
    assert correlation_id.get() is None


def test_correlation_id_is_cleared_after_a_database_failure() -> None:
    event = make_event()
    method = SimpleNamespace(delivery_tag=TAG, routing_key=event["eventType"])
    failure = OperationalError("INSERT", {}, Exception("database is down"))
    with (
        patch("app.consumer.crud.create_notification_from_event", side_effect=failure),
        pytest.raises(OperationalError),
    ):
        handle_delivery(MagicMock(), method, None, json.dumps(event).encode())
    assert correlation_id.get() is None
