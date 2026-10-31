import logging
import signal
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pika
from pika.exceptions import AMQPError
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.core.db import engine
from app.core.logs import configure_logging, correlation_id, one_line
from app.models import EVENT_CATEGORIES, BuddyEvent

# Not __name__: this runs with `python -m`, which would log it as __main__.
logger = logging.getLogger("app.consumer")

EVENTS_EXCHANGE = "cra.events"
DEAD_EXCHANGE = "cra.dead"
QUEUE = "notifications.events"
DEAD_QUEUE = "notifications.dead"
RETRY_SECONDS = 3
OUTCOME_LABELS = {
    "stored": "Stored",
    "duplicate": "Ignored duplicate",
    "muted": "Muted",
}
# Compose's healthcheck reads this, because the consumer serves no HTTP.
READY_FILE = Path(tempfile.gettempdir()) / "notification-consumer-ready"


def declare_topology(channel: Any) -> None:
    """Declare the exchanges, queues and bindings this consumer needs.

    Publishing fails until this has run once, because the contract keeps
    an event in the publisher's outbox until it is routed.

    Args:
        channel (Any): An open channel.
    """
    channel.exchange_declare(EVENTS_EXCHANGE, exchange_type="topic", durable=True)
    channel.exchange_declare(DEAD_EXCHANGE, exchange_type="topic", durable=True)
    channel.queue_declare(DEAD_QUEUE, durable=True)
    channel.queue_bind(DEAD_QUEUE, DEAD_EXCHANGE, routing_key="#")
    channel.queue_declare(
        QUEUE, durable=True, arguments={"x-dead-letter-exchange": DEAD_EXCHANGE}
    )
    for event_type in EVENT_CATEGORIES:
        channel.queue_bind(QUEUE, EVENTS_EXCHANGE, routing_key=event_type)


def handle_delivery(channel: Any, method: Any, _properties: Any, body: bytes) -> None:
    """Store one delivered event, acknowledging only after the commit.

    An invalid message goes to the dead-letter queue. A database failure
    leaves the delivery unacknowledged, so closing the channel requeues it.

    Args:
        channel (Any): The channel the message arrived on.
        method (Any): Delivery details, with the tag and routing key.
        _properties (Any): Message properties, which are not used.
        body (bytes): The raw message.

    Raises:
        SQLAlchemyError: If the database cannot store the event.
    """
    try:
        event = BuddyEvent.model_validate_json(body, strict=True)
    except ValidationError as error:
        # Locations and types only: the input is unvalidated and may be private.
        problems = [
            (detail["loc"], detail["type"])
            for detail in error.errors(include_input=False, include_url=False)
        ]
        logger.warning(
            "Rejected invalid message on %s: %s", method.routing_key, problems
        )
        channel.basic_reject(method.delivery_tag, requeue=False)
        return

    token = correlation_id.set(str(event.correlation_id))
    try:
        if event.event_type != method.routing_key:
            logger.warning(
                "Rejected event %s: routing key %s does not match type %s",
                event.event_id,
                method.routing_key,
                event.event_type,
            )
            channel.basic_reject(method.delivery_tag, requeue=False)
            return
        try:
            with Session(engine) as session:
                outcome = crud.create_notification_from_event(
                    session=session, event=event
                )
        except SQLAlchemyError as error:
            logger.error(
                "Could not store event %s: %s", event.event_id, one_line(error)
            )
            raise
        channel.basic_ack(method.delivery_tag)
        logger.info("%s event %s", OUTCOME_LABELS[outcome], event.event_id)
    finally:
        correlation_id.reset(token)


def consume() -> None:
    """Consume events until the broker or the database fails.

    Raises:
        AMQPError: If the broker connection or channel fails.
        SQLAlchemyError: If the database cannot store an event.
        OSError: If the broker's socket fails.
    """
    parameters = pika.ConnectionParameters(
        host=settings.RABBITMQ_HOST,
        port=settings.RABBITMQ_PORT,
        virtual_host=settings.RABBITMQ_VHOST,
        credentials=pika.PlainCredentials(
            settings.RABBITMQ_USER, settings.RABBITMQ_PASSWORD
        ),
    )
    # pika annotates __exit__ with the wrong types, but it works at runtime.
    with pika.BlockingConnection(parameters) as connection:  # ty: ignore[invalid-context-manager]
        channel = connection.channel()
        declare_topology(channel)
        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(QUEUE, handle_delivery)
        READY_FILE.touch()
        logger.info("Consuming %s", QUEUE)
        try:
            channel.start_consuming()
        finally:
            READY_FILE.unlink(missing_ok=True)


def main() -> None:
    """Run the consumer until the process is told to stop."""
    configure_logging()
    READY_FILE.unlink(missing_ok=True)
    # As PID 1 Python would ignore SIGTERM, and Compose would wait to kill it.
    for stop_signal in (signal.SIGTERM, signal.SIGINT):
        signal.signal(stop_signal, lambda *_: sys.exit(0))
    while True:
        try:
            consume()
        except (AMQPError, SQLAlchemyError, OSError) as error:
            logger.warning(
                "Consumer stopped, retrying in %s seconds: %s: %s",
                RETRY_SECONDS,
                type(error).__name__,
                one_line(error),
            )
            time.sleep(RETRY_SECONDS)


if __name__ == "__main__":
    main()
