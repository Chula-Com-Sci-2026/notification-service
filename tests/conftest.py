import os

# Set before any app import, so the engine binds to a database this suite may
# drop, the consumer uses its own vhost, and tokens use a test-only key.
os.environ["POSTGRES_DB"] = "notification_test"
os.environ["RABBITMQ_VHOST"] = "notification_test"
os.environ["ACCESS_TOKEN_SECRET"] = "test-only-secret-" + "x" * 64

from collections.abc import Generator  # noqa: E402

import psycopg  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlmodel import Session, create_engine  # noqa: E402

from app.api.deps import get_db  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.db import engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def test_database() -> None:
    """Recreate the test database using the real migrations."""
    with psycopg.connect(
        host=settings.POSTGRES_SERVER,
        port=settings.POSTGRES_PORT,
        user=settings.POSTGRES_USER,
        password=settings.POSTGRES_PASSWORD,
        dbname="postgres",
        autocommit=True,
    ) as connection:
        connection.execute(
            f'DROP DATABASE IF EXISTS "{settings.POSTGRES_DB}" WITH (FORCE)'
        )
        connection.execute(f'CREATE DATABASE "{settings.POSTGRES_DB}"')
    command.upgrade(Config("alembic.ini"), "head")


@pytest.fixture
def db() -> Generator[Session]:
    with Session(engine) as session:
        yield session


@pytest.fixture(scope="module")
def client() -> Generator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.fixture
def database_down() -> Generator[None]:
    """Route requests to a database nothing is listening on."""
    dead = create_engine(
        "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none",
        connect_args={"connect_timeout": 1},
    )

    def dead_session() -> Generator[Session]:
        with Session(dead) as session:
            yield session

    app.dependency_overrides[get_db] = dead_session
    yield
    app.dependency_overrides.clear()
