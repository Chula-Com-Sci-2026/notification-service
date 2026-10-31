import uuid

from sqlalchemy import DateTime, Uuid, func, literal, tuple_, update
from sqlmodel import Session, col, select

from app.models import Notification


def list_notifications(
    *,
    session: Session,
    recipient_id: uuid.UUID,
    limit: int,
    before: uuid.UUID | None = None,
) -> tuple[list[Notification], uuid.UUID | None]:
    """Return one page of a runner's notifications, newest first.

    Args:
        session (Session): Database session.
        recipient_id (uuid.UUID): Runner whose inbox to read.
        limit (int): Maximum notifications on the page.
        before (uuid.UUID, optional): Return notifications older than this
            one. Another runner's ID gives an empty page, so it reveals
            nothing. Defaults to None, the newest page.

    Returns:
        tuple[list[Notification], uuid.UUID | None]: The page, and the
        cursor for the next page, or None on the last page.
    """
    position = tuple_(col(Notification.occurred_at), col(Notification.id))
    statement = select(Notification).where(
        col(Notification.recipient_id) == recipient_id
    )
    if before is not None:
        anchor = session.exec(
            select(Notification.occurred_at, Notification.id).where(
                col(Notification.id) == before,
                col(Notification.recipient_id) == recipient_id,
            )
        ).first()
        if anchor is None:
            return [], None
        statement = statement.where(
            position
            < tuple_(
                literal(anchor[0], DateTime(timezone=True)), literal(anchor[1], Uuid())
            )
        )
    # One extra row shows whether another page exists without a second query.
    rows = session.exec(
        statement.order_by(
            col(Notification.occurred_at).desc(), col(Notification.id).desc()
        ).limit(limit + 1)
    ).all()
    page = list(rows[:limit])
    return page, page[-1].id if len(rows) > limit else None


def count_unread(*, session: Session, recipient_id: uuid.UUID) -> int:
    """Count a runner's unread notifications.

    Args:
        session (Session): Database session.
        recipient_id (uuid.UUID): Runner whose inbox to count.

    Returns:
        int: Number of unread notifications.
    """
    return session.exec(
        select(func.count())
        .select_from(Notification)
        .where(
            col(Notification.recipient_id) == recipient_id,
            col(Notification.read_at).is_(None),
        )
    ).one()


def mark_notification_read(
    *, session: Session, notification_id: uuid.UUID, recipient_id: uuid.UUID
) -> Notification | None:
    """Mark a runner's notification as read, keeping the first read time.

    Args:
        session (Session): Database session.
        notification_id (uuid.UUID): Notification to mark.
        recipient_id (uuid.UUID): Runner who must own the notification.

    Returns:
        Notification | None: The updated notification, or None if it does
        not exist or belongs to another runner.
    """
    # One atomic statement, so concurrent calls cannot overwrite the first time.
    notification = session.exec(
        update(Notification)
        .where(
            col(Notification.id) == notification_id,
            col(Notification.recipient_id) == recipient_id,
        )
        .values(read_at=func.coalesce(Notification.read_at, func.now()))
        .returning(Notification)
    ).scalar_one_or_none()
    session.commit()
    return notification
