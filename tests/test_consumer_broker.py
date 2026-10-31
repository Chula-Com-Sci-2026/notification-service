"""Run the real consumer process against real RabbitMQ and PostgreSQL."""

import uuid
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.consumer import DEAD_EXCHANGE, DEAD_QUEUE, EVENTS_EXCHANGE, QUEUE
from app.core.config import settings
from tests.utils.broker import Broker, ConsumerProcess, wait_until
from tests.utils.events import make_event
from tests.utils.tokens import auth_headers

URL = f"{settings.API_V1_STR}/notifications"


@pytest.fixture(scope="module", autouse=True)
def broker() -> Broker:
    instance = Broker()
    instance.reset_vhost()
    return instance


@pytest.fixture
def consumer(tmp_path: Path) -> Generator[ConsumerProcess]:
    process = ConsumerProcess(tmp_path / "consumer.log")
    process.start()
    yield process
    process.stop()


def inbox(client: TestClient, runner: uuid.UUID) -> list[dict[str, Any]]:
    return client.get(URL, headers=auth_headers(runner)).json()["items"]


def wait_for_inbox(client: TestClient, runner: uuid.UUID, count: int = 1) -> None:
    wait_until(lambda: len(inbox(client, runner)) >= count)


def in_queue(broker: Broker, queue: str, marker: str) -> bool:
    return any(marker in message["payload"] for message in broker.peek(queue))


@pytest.mark.usefixtures("consumer")
def test_topology_matches_the_contract(broker: Broker) -> None:
    events = broker.get(f"exchanges/{EVENTS_EXCHANGE}")
    assert (events["type"], events["durable"]) == ("topic", True)
    dead = broker.get(f"exchanges/{DEAD_EXCHANGE}")
    assert (dead["type"], dead["durable"]) == ("topic", True)
    assert any(
        binding["source"] == DEAD_EXCHANGE
        for binding in broker.get(f"queues/{DEAD_QUEUE}/bindings")
    )

    queue = broker.get(f"queues/{QUEUE}")
    assert queue["durable"] is True
    assert queue["arguments"]["x-dead-letter-exchange"] == DEAD_EXCHANGE
    assert broker.get(f"queues/{DEAD_QUEUE}")["durable"] is True

    routing_keys = {
        binding["routing_key"]
        for binding in broker.get(f"queues/{QUEUE}/bindings")
        if binding["source"] == EVENTS_EXCHANGE
    }
    assert routing_keys == {"BuddyRequestSent", "BuddyRequestAnswered"}


def test_sent_event_reaches_only_the_recipient(
    client: TestClient, broker: Broker, consumer: ConsumerProcess
) -> None:
    sender, recipient = uuid.uuid4(), uuid.uuid4()
    event = make_event(sender_id=sender, recipient_id=recipient)

    assert broker.publish(event, "BuddyRequestSent") is True

    wait_for_inbox(client, recipient)
    item = inbox(client, recipient)[0]
    assert item["type"] == "BuddyRequestSent"
    assert item["data"]["senderId"] == str(sender)
    assert inbox(client, sender) == []
    # Checked on the real process, where `python -m` makes __name__ __main__.
    assert (
        f"INFO app.consumer correlation_id={event['correlationId']} Stored"
        in consumer.logs()
    )


@pytest.mark.usefixtures("consumer")
def test_answered_event_reaches_only_the_original_sender(
    client: TestClient, broker: Broker
) -> None:
    sender, answerer = uuid.uuid4(), uuid.uuid4()
    event = make_event(
        "BuddyRequestAnswered",
        sender_id=sender,
        recipient_id=answerer,
        status="rejected",
    )

    assert broker.publish(event, "BuddyRequestAnswered") is True

    wait_for_inbox(client, sender)
    assert inbox(client, sender)[0]["data"]["status"] == "rejected"
    assert inbox(client, answerer) == []


@pytest.mark.usefixtures("consumer")
def test_redelivered_event_creates_one_notification(
    client: TestClient, broker: Broker
) -> None:
    runner = uuid.uuid4()
    event = make_event(recipient_id=runner)
    later = make_event(recipient_id=runner)

    broker.publish(event, "BuddyRequestSent")
    broker.publish(event, "BuddyRequestSent")
    # Handled in order, so once this arrives the duplicate has been handled too.
    broker.publish(later, "BuddyRequestSent")

    wait_for_inbox(client, runner, count=2)
    assert len(inbox(client, runner)) == 2


@pytest.mark.parametrize(
    ("make_body", "routing_key"),
    [
        (lambda marker: f"not json {marker}", "BuddyRequestSent"),
        (lambda marker: make_event(eventId=marker, version=2), "BuddyRequestSent"),
        (
            lambda marker: make_event(eventId=marker, status="accepted"),
            "BuddyRequestSent",
        ),
        (lambda marker: make_event(eventId=marker), "BuddyRequestAnswered"),
    ],
    ids=["bad json", "wrong version", "wrong status", "routing key mismatch"],
)
@pytest.mark.usefixtures("consumer")
def test_invalid_message_goes_to_the_dead_queue_and_nothing_stops(
    client: TestClient, broker: Broker, make_body: Any, routing_key: str
) -> None:
    marker = str(uuid.uuid4())
    runner = uuid.uuid4()

    assert broker.publish(make_body(marker), routing_key) is True
    wait_until(lambda: in_queue(broker, DEAD_QUEUE, marker))

    broker.publish(make_event(recipient_id=runner), "BuddyRequestSent")
    wait_for_inbox(client, runner)


@pytest.mark.usefixtures("consumer")
def test_unbound_routing_key_is_reported_as_not_routed(broker: Broker) -> None:
    assert broker.publish(make_event(), "SomethingElse") is False


def test_events_wait_in_the_queue_while_the_consumer_is_down(
    client: TestClient, broker: Broker, tmp_path: Path
) -> None:
    first = ConsumerProcess(tmp_path / "first.log")
    first.start()
    first.stop()

    runner = uuid.uuid4()
    event = make_event(recipient_id=runner)
    assert broker.publish(event, "BuddyRequestSent") is True
    wait_until(lambda: in_queue(broker, QUEUE, event["eventId"]))
    assert inbox(client, runner) == []

    second = ConsumerProcess(tmp_path / "second.log")
    second.start()
    try:
        wait_for_inbox(client, runner)
    finally:
        second.stop()


def test_database_failure_keeps_the_event_until_recovery(
    client: TestClient, broker: Broker, tmp_path: Path
) -> None:
    runner = uuid.uuid4()
    event = make_event(recipient_id=runner)

    broken = ConsumerProcess(tmp_path / "broken.log", POSTGRES_PORT="1")
    broken.start()
    try:
        broker.publish(event, "BuddyRequestSent")
        # Two failures show the event came back after the first one.
        wait_until(
            lambda: broken.logs().count("Could not store event") >= 2, timeout=60
        )
    finally:
        broken.stop()

    assert inbox(client, runner) == []
    assert not in_queue(broker, DEAD_QUEUE, event["eventId"])
    wait_until(lambda: in_queue(broker, QUEUE, event["eventId"]))

    healthy = ConsumerProcess(tmp_path / "healthy.log")
    healthy.start()
    try:
        wait_for_inbox(client, runner)
    finally:
        healthy.stop()
    assert len(inbox(client, runner)) == 1
