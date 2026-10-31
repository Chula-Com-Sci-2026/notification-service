import uuid
from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel
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


class CamelModel(BaseModel):
    """Base for API bodies, which use camelCase like the event contracts."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ApiError(CamelModel):
    """Error body for every failure except FastAPI's native 422.

    Attributes:
        code: Stable uppercase code for clients to branch on.
        message: Human-readable explanation.
    """

    code: str
    message: str


class NotificationPublic(CamelModel):
    """Notification as returned to the runner who owns it.

    Holds no rendered text: events carry only IDs, and the client renders
    Thai or English (NFR-6.3) and looks up display names through Profile.

    Attributes:
        id: Notification ID.
        type: Event type, such as `BuddyRequestSent`.
        category: Category the runner can turn off.
        data: Event payload as published.
        occurred_at: When the event happened.
        read_at: When the runner first read it, or None while unread.
    """

    id: uuid.UUID
    type: str
    category: str
    data: dict[str, Any]
    occurred_at: datetime
    read_at: datetime | None

    @classmethod
    def from_row(cls, row: Notification) -> Self:
        """Build the public view of a stored notification.

        Args:
            row (Notification): The stored notification.

        Returns:
            Self: The view to return to the client.
        """
        return cls(
            id=row.id,
            type=row.event_type,
            category=row.category,
            data=row.payload,
            occurred_at=row.occurred_at,
            read_at=row.read_at,
        )


class NotificationsPublic(CamelModel):
    """One page of a runner's inbox.

    Attributes:
        items: Notifications on this page, newest first.
        unread_count: Unread notifications across the whole inbox.
        next_cursor: Value for `before` to fetch the next page, or None on
            the last page.
    """

    items: list[NotificationPublic]
    unread_count: int
    next_cursor: uuid.UUID | None
