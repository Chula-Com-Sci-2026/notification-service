import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from app.models import BuddyEvent
from tests.utils.events import make_event

# Copied from running-buddy-contracts, so the suite runs without a sibling checkout.
SCHEMA = Draft202012Validator(
    json.loads(
        (Path(__file__).parent / "contracts" / "buddy-events.schema.json").read_text()
    )
)


def without(field: str) -> dict[str, Any]:
    event = make_event()
    del event[field]
    return event


def without_payload_field(field: str) -> dict[str, Any]:
    event = make_event()
    del event["payload"][field]
    return event


VALID = {
    "sent": lambda: make_event(),
    "accepted": lambda: make_event("BuddyRequestAnswered", status="accepted"),
    "rejected": lambda: make_event("BuddyRequestAnswered", status="rejected"),
    "offset timestamp": lambda: make_event(occurredAt="2026-10-30T17:00:00+07:00"),
    "z timestamp": lambda: make_event(occurredAt="2026-10-30T10:00:00Z"),
}

# Rules the schema states directly, so the model and the schema must both refuse.
REJECTED_BY_SCHEMA = {
    "no eventId": lambda: without("eventId"),
    "no eventType": lambda: without("eventType"),
    "no version": lambda: without("version"),
    "no occurredAt": lambda: without("occurredAt"),
    "no correlationId": lambda: without("correlationId"),
    "no payload": lambda: without("payload"),
    "no requestId": lambda: without_payload_field("requestId"),
    "no senderId": lambda: without_payload_field("senderId"),
    "no recipientId": lambda: without_payload_field("recipientId"),
    "no status": lambda: without_payload_field("status"),
    "version 2": lambda: make_event(version=2),
    "version as text": lambda: make_event(version="1"),
    "unknown type": lambda: make_event(eventType="BuddyRequestDeleted"),
    "sent but accepted": lambda: make_event(status="accepted"),
    "answered but pending": lambda: make_event(
        "BuddyRequestAnswered", status="pending"
    ),
    "unknown status": lambda: make_event(status="declined"),
    "timestamp as number": lambda: make_event(occurredAt=1793000000),
    "payload not an object": lambda: make_event(payload="pending"),
}

# `format` is advisory in JSON Schema, so only the model enforces these.
REJECTED_BY_FORMAT = {
    "eventId not a uuid": lambda: make_event(eventId="event-1"),
    "correlationId not a uuid": lambda: make_event(correlationId="abc"),
    "timestamp not a date": lambda: make_event(occurredAt="yesterday"),
    "timestamp with no zone": lambda: make_event(occurredAt="2026-10-30T10:00:00"),
}


@pytest.mark.parametrize("build", VALID.values(), ids=VALID.keys())
def test_valid_events_pass_the_schema_and_the_model(build: Any) -> None:
    event = build()
    SCHEMA.validate(event)
    BuddyEvent.model_validate_json(json.dumps(event), strict=True)


@pytest.mark.parametrize(
    "build", REJECTED_BY_SCHEMA.values(), ids=REJECTED_BY_SCHEMA.keys()
)
def test_model_refuses_what_the_schema_refuses(build: Any) -> None:
    event = build()
    assert not SCHEMA.is_valid(event), "This case no longer breaks the schema"
    with pytest.raises(ValidationError):
        BuddyEvent.model_validate_json(json.dumps(event), strict=True)


@pytest.mark.parametrize(
    "build", REJECTED_BY_FORMAT.values(), ids=REJECTED_BY_FORMAT.keys()
)
def test_model_refuses_bad_formats(build: Any) -> None:
    with pytest.raises(ValidationError):
        BuddyEvent.model_validate_json(json.dumps(build()), strict=True)


@pytest.mark.parametrize("body", [b"", b"not json", b"[]", b"\xff\xfe"])
def test_model_refuses_bodies_that_are_not_events(body: bytes) -> None:
    with pytest.raises(ValidationError):
        BuddyEvent.model_validate_json(body, strict=True)


def test_snake_case_is_not_the_contract() -> None:
    event = make_event()
    event["event_id"] = event.pop("eventId")
    with pytest.raises(ValidationError):
        BuddyEvent.model_validate_json(json.dumps(event), strict=True)


def test_sent_event_notifies_the_recipient() -> None:
    sender, recipient = uuid.uuid4(), uuid.uuid4()
    event = make_event(sender_id=sender, recipient_id=recipient)
    parsed = BuddyEvent.model_validate_json(json.dumps(event), strict=True)
    assert parsed.notification_recipient_id == recipient


@pytest.mark.parametrize("status", ["accepted", "rejected"])
def test_answered_event_notifies_the_original_sender(status: str) -> None:
    sender, answerer = uuid.uuid4(), uuid.uuid4()
    event = make_event(
        "BuddyRequestAnswered", sender_id=sender, recipient_id=answerer, status=status
    )
    parsed = BuddyEvent.model_validate_json(json.dumps(event), strict=True)
    assert parsed.notification_recipient_id == sender


@pytest.mark.parametrize("event_type", ["BuddyRequestSent", "BuddyRequestAnswered"])
def test_both_event_types_have_the_buddy_category(event_type: str) -> None:
    parsed = BuddyEvent.model_validate_json(
        json.dumps(make_event(event_type)), strict=True
    )
    assert parsed.category == "buddy_requests"


def test_new_fields_from_a_publisher_are_tolerated_but_not_kept() -> None:
    event = make_event(traceId="abc")
    event["payload"]["note"] = "private text"
    parsed = BuddyEvent.model_validate_json(json.dumps(event), strict=True)
    assert "note" not in parsed.payload.model_dump(by_alias=True)
