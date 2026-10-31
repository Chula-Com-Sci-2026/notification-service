import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from app import crud
from app.api.deps import CurrentRunnerId, SessionDep
from app.models import ApiError, NotificationPublic, NotificationsPublic

router = APIRouter(
    prefix="/notifications",
    tags=["notifications"],
    responses={
        status.HTTP_401_UNAUTHORIZED: {"model": ApiError},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ApiError},
    },
)


@router.get("")
def notifications(
    session: SessionDep,
    runner_id: CurrentRunnerId,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before: uuid.UUID | None = None,
) -> NotificationsPublic:
    """List the runner's notifications, newest first."""
    rows, next_cursor = crud.list_notifications(
        session=session, recipient_id=runner_id, limit=limit, before=before
    )
    return NotificationsPublic(
        items=[NotificationPublic.from_row(row) for row in rows],
        unread_count=crud.count_unread(session=session, recipient_id=runner_id),
        next_cursor=next_cursor,
    )


@router.patch(
    "/{notification_id}/read",
    responses={status.HTTP_404_NOT_FOUND: {"model": ApiError}},
)
def read(
    notification_id: uuid.UUID, session: SessionDep, runner_id: CurrentRunnerId
) -> NotificationPublic:
    """Mark one of the runner's notifications as read."""
    notification = crud.mark_notification_read(
        session=session, notification_id=notification_id, recipient_id=runner_id
    )
    if notification is None:
        # Same answer for another runner's ID, so it cannot be probed.
        raise HTTPException(status_code=404, detail="Notification not found")
    return NotificationPublic.from_row(notification)
