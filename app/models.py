import uuid
from datetime import datetime
from typing import Any, Literal, Self, get_args

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    StrictBool,
    field_validator,
    model_validator,
)
from pydantic.alias_generators import to_camel
from sqlalchemy import DateTime, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

NotificationCategory = Literal[
    "buddy_requests",
    "run_invitations",
    "run_changes",
    "reminders",
    "weather_alerts",
    "attendance_prompts",
]
CATEGORIES: tuple[NotificationCategory, ...] = get_args(NotificationCategory)
# FR-9.2: runners always hear about run changes and cancellations.
LOCKED_CATEGORIES = frozenset({"run_changes"})
EVENT_CATEGORIES = {
    "BuddyRequestSent": "buddy_requests",
    "BuddyRequestAnswered": "buddy_requests",
}


class EventModel(BaseModel):
    """Base for broker messages, which must use the contract's camelCase."""

    model_config = ConfigDict(alias_generator=to_camel)


class BuddyEventPayload(EventModel):
    """Payload of a buddy event, version 1.

    Attributes:
        request_id: The buddy request.
        sender_id: Runner who sent the request.
        recipient_id: Runner the request was sent to.
        status: Request status after this event.
    """

    request_id: uuid.UUID
    sender_id: uuid.UUID
    recipient_id: uuid.UUID
    status: Literal["pending", "accepted", "rejected"]


class BuddyEvent(EventModel):
    """Buddy event envelope, version 1, from `buddy-events.schema.json`.

    Attributes:
        event_id: Unique ID, stable across redeliveries.
        event_type: What happened, which is also the routing key.
        version: Envelope version.
        occurred_at: When it happened.
        correlation_id: ID that ties this event to the originating request.
        payload: Details of the buddy request.
    """

    event_id: uuid.UUID
    event_type: Literal["BuddyRequestSent", "BuddyRequestAnswered"]
    version: Literal[1]
    occurred_at: AwareDatetime
    correlation_id: uuid.UUID
    payload: BuddyEventPayload

    @model_validator(mode="after")
    def _status_fits_event_type(self) -> Self:
        allowed = (
            ("pending",)
            if self.event_type == "BuddyRequestSent"
            else ("accepted", "rejected")
        )
        if self.payload.status not in allowed:
            raise ValueError(
                f"{self.event_type} cannot have status {self.payload.status}"
            )
        return self

    @property
    def notification_recipient_id(self) -> uuid.UUID:
        """Return the runner to notify.

        A sent request goes to its recipient. An answer goes back to the
        original sender, because `recipientId` is the person who answered.

        Returns:
            uuid.UUID: The runner who should see this notification.
        """
        if self.event_type == "BuddyRequestSent":
            return self.payload.recipient_id
        return self.payload.sender_id

    @property
    def category(self) -> str:
        """Return the category a runner can turn off for this event.

        Returns:
            str: The notification category.
        """
        return EVENT_CATEGORIES[self.event_type]


class Notification(SQLModel, table=True):
    """In-app notification for one runner, created from one domain event.

    Attributes:
        id: Notification ID exposed to clients.
        event_id: `eventId` from the event envelope.
        recipient_id: Runner who owns this notification.
        event_type: `eventType` from the event envelope.
        category: Category the runner can turn off (FR-9.2).
        payload: Contract fields of the event payload, so a new event type
            needs no schema change.
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


class NotificationPreference(SQLModel, table=True):
    """A runner's choice for one category. A missing row means it is on.

    Attributes:
        recipient_id: Runner who made the choice.
        category: The notification category.
        enabled: Whether the runner receives this category.
    """

    __tablename__ = "notification_preferences"

    recipient_id: uuid.UUID = Field(primary_key=True)
    category: str = Field(primary_key=True, max_length=32)
    enabled: bool


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
        data: Contract fields of the event payload.
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


class PreferencePublic(CamelModel):
    """A runner's setting for one category.

    Attributes:
        category: The notification category.
        enabled: Whether the runner receives this category.
        locked: Whether the runner is unable to turn it off.
    """

    category: NotificationCategory
    enabled: bool
    locked: bool


class PreferencesPublic(CamelModel):
    """A runner's setting for every category.

    Attributes:
        items: One entry per category, in a stable order.
    """

    items: list[PreferencePublic]

    @classmethod
    def from_choices(cls, choices: dict[NotificationCategory, bool]) -> Self:
        """Build the public view of a runner's settings.

        Args:
            choices (dict[NotificationCategory, bool]): Whether each category
                is on.

        Returns:
            Self: The view to return to the client.
        """
        return cls(
            items=[
                PreferencePublic(
                    category=category,
                    enabled=enabled,
                    locked=category in LOCKED_CATEGORIES,
                )
                for category, enabled in choices.items()
            ]
        )


class PreferencesUpdate(CamelModel):
    """Request to change some categories, leaving the rest as they are.

    Attributes:
        categories: The categories to change and whether each should be on.
    """

    categories: dict[NotificationCategory, StrictBool] = Field(min_length=1)

    @field_validator("categories")
    @classmethod
    def _locked_categories_stay_on(
        cls, categories: dict[NotificationCategory, bool]
    ) -> dict[NotificationCategory, bool]:
        for category, enabled in categories.items():
            if category in LOCKED_CATEGORIES and not enabled:
                raise ValueError(f"{category} cannot be turned off")
        return categories
