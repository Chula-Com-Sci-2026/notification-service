import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class Notification(SQLModel, table=True):
    """In-app notification for one runner, created from one domain event.

    Attributes:
        id: Notification ID exposed to clients.
        event_id: `eventId` from the event envelope.
        recipient_id: Runner who owns this notification.
        event_type: `eventType` from the event envelope.
        category: Category the runner can turn off (FR-9.2).
        payload: Event payload as published, so a new event type needs no
            schema change.
        occurred_at: `occurredAt` from the event envelope.
        read_at: When the runner first read it, or None while unread.
    """

    __tablename__ = "notifications"
    __table_args__ = (
        # Delivery is at least once, so a redelivered event must not add a row.
        UniqueConstraint(
            "event_id", "recipient_id", name="uq_notifications_event_recipient"
        ),
        Index("ix_notifications_inbox", "recipient_id", "occurred_at", "id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    event_id: uuid.UUID
    recipient_id: uuid.UUID
    event_type: str = Field(max_length=64)
    category: str = Field(max_length=32)
    payload: dict[str, Any] = Field(sa_type=JSONB)
    occurred_at: datetime = Field(sa_type=DateTime(timezone=True))
    read_at: datetime | None = Field(default=None, sa_type=DateTime(timezone=True))
