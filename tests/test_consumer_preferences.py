import logging
import uuid

import pytest
from sqlmodel import Session

from app import crud
from app.core.db import engine
from app.models import NotificationPreference
from tests.test_consumer import TAG, deliver, stored_for
from tests.utils.events import make_event


def mute(runner: uuid.UUID, category: str = "buddy_requests") -> None:
    with Session(engine) as session:
        crud.update_preferences(
            session=session, recipient_id=runner, choices={category: False}
        )


def unmute(runner: uuid.UUID, category: str = "buddy_requests") -> None:
    with Session(engine) as session:
        crud.update_preferences(
            session=session, recipient_id=runner, choices={category: True}
        )


def test_muted_event_is_acked_and_not_stored(caplog: pytest.LogCaptureFixture) -> None:
    runner = uuid.uuid4()
    mute(runner)
    event = make_event(recipient_id=runner)
    with caplog.at_level(logging.INFO, logger="app.consumer"):
        channel = deliver(event)
    channel.basic_ack.assert_called_once_with(TAG)
    channel.basic_reject.assert_not_called()
    assert stored_for(runner) == []
    assert f"Muted event {event['eventId']}" in caplog.text


def test_unmuting_applies_to_later_events_and_does_not_backfill() -> None:
    runner = uuid.uuid4()
    mute(runner)
    missed = make_event(recipient_id=runner)
    deliver(missed)
    unmute(runner)
    later = make_event(recipient_id=runner)
    deliver(later)
    assert [str(row.event_id) for row in stored_for(runner)] == [later["eventId"]]


def test_a_sent_event_checks_the_recipients_setting_not_the_senders() -> None:
    sender, recipient = uuid.uuid4(), uuid.uuid4()
    mute(sender)
    deliver(make_event(sender_id=sender, recipient_id=recipient))
    assert len(stored_for(recipient)) == 1


def test_an_answer_checks_the_original_senders_setting_not_the_answerers() -> None:
    sender, answerer = uuid.uuid4(), uuid.uuid4()
    mute(answerer)
    deliver(make_event("BuddyRequestAnswered", sender_id=sender, recipient_id=answerer))
    assert len(stored_for(sender)) == 1


def test_an_answer_to_a_sender_who_muted_is_not_stored() -> None:
    sender, answerer = uuid.uuid4(), uuid.uuid4()
    mute(sender)
    channel = deliver(
        make_event("BuddyRequestAnswered", sender_id=sender, recipient_id=answerer)
    )
    channel.basic_ack.assert_called_once_with(TAG)
    assert stored_for(sender) == []


def test_muting_another_category_does_not_mute_this_one() -> None:
    runner = uuid.uuid4()
    mute(runner, "reminders")
    deliver(make_event(recipient_id=runner))
    assert len(stored_for(runner)) == 1


def test_a_locked_category_is_on_even_if_a_row_says_otherwise() -> None:
    runner = uuid.uuid4()
    with Session(engine) as session:
        session.add(
            NotificationPreference(
                recipient_id=runner, category="run_changes", enabled=False
            )
        )
        session.commit()
        assert crud.category_enabled(
            session=session, recipient_id=runner, category="run_changes"
        )
        assert crud.list_preferences(session=session, recipient_id=runner)[
            "run_changes"
        ]


def test_redelivery_of_a_stored_event_after_muting_stores_nothing_new() -> None:
    runner = uuid.uuid4()
    event = make_event(recipient_id=runner)
    deliver(event)
    mute(runner)
    channel = deliver(event)
    channel.basic_ack.assert_called_once_with(TAG)
    assert len(stored_for(runner)) == 1
