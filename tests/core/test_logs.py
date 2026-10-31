import io
import logging

from sqlalchemy.exc import OperationalError

from app.core.logs import LOG_FORMAT, correlation_id, one_line


def formatted_line(message: str) -> str:
    """Log one line through the service's format and return the text."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger = logging.getLogger("tests.logs")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        logger.info(message)
    finally:
        logger.removeHandler(handler)
    return stream.getvalue()


def test_every_line_names_the_current_correlation_id() -> None:
    token = correlation_id.set("abc-123")
    try:
        line = formatted_line("hello")
    finally:
        correlation_id.reset(token)
    assert "correlation_id=abc-123 hello" in line


def test_a_line_with_no_correlation_id_still_formats() -> None:
    assert "correlation_id=- hello" in formatted_line("hello")


def test_one_line_keeps_only_the_drivers_message() -> None:
    error = OperationalError("SELECT 1", {"p": "x"}, Exception("server\n\tis  down"))
    assert one_line(error) == "server is down"


def test_one_line_handles_errors_without_a_driver_message() -> None:
    assert one_line(ValueError("two\nlines")) == "two lines"
