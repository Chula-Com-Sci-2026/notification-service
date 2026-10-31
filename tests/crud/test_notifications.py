import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from sqlmodel import Session

from app import crud
from app.core.db import engine
from tests.utils.notification import create_notification


def test_concurrent_reads_keep_one_time(db: Session) -> None:
    runner = uuid.uuid4()
    notification_id = create_notification(db, runner).id

    def mark_read(_: int) -> datetime | None:
        with Session(engine) as session:
            notification = crud.mark_notification_read(
                session=session, notification_id=notification_id, recipient_id=runner
            )
            return notification.read_at if notification else None

    with ThreadPoolExecutor(max_workers=8) as pool:
        times = set(pool.map(mark_read, range(8)))

    assert len(times) == 1
    assert None not in times


def test_marking_read_needs_the_owner(db: Session) -> None:
    stored = create_notification(db, uuid.uuid4())
    result = crud.mark_notification_read(
        session=db, notification_id=stored.id, recipient_id=uuid.uuid4()
    )
    assert result is None
    db.refresh(stored)
    assert stored.read_at is None
