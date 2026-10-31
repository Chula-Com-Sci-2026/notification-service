from sqlmodel import create_engine

from app.core.config import settings

engine = create_engine(
    str(settings.SQLALCHEMY_DATABASE_URI),
    # A restarted database must not fail requests on stale pooled connections.
    pool_pre_ping=True,
    # Answer 503 quickly instead of holding the request until the TCP timeout.
    connect_args={"connect_timeout": 3},
)
