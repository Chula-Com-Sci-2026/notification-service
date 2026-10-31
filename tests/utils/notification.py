import uuid
from datetime import UTC, datetime

from sqlmodel import Session

from app.models import Notification


def create_notification(
    db: Session,
    recipient_id: uuid.UUID,
    *,
    occurred_at: datetime | None = None,
    read_at: datetime | None = None,
) -> Notification:
    """Insert a buddy request notification for a runner.

    Args:
        db (Session): Database session.
        recipient_id (uuid.UUID): Runner who owns the notification.
        occurred_at (datetime, optional): Event time. Defaults to now.
        read_at (datetime, optional): First read time. Defaults to unread.

    Returns:
        Notification: The stored notification.
    """
    notification = Notification(
        event_id=uuid.uuid4(),
        recipient_id=recipient_id,
        event_type="BuddyRequestSent",
        category="buddy_requests",
        payload={
            "requestId": str(uuid.uuid4()),
            "senderId": str(uuid.uuid4()),
            "recipientId": str(recipient_id),
            "status": "pending",
        },
        occurred_at=occurred_at or datetime.now(UTC),
        read_at=read_at,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification
