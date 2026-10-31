import logging
import sys
from contextvars import ContextVar
from typing import Any

correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

LOG_FORMAT = (
    "%(asctime)s %(levelname)s %(name)s correlation_id=%(correlation_id)s %(message)s"
)


def _make_record(*args: Any, **kwargs: Any) -> logging.LogRecord:
    """Build a log record that names the current correlation ID.

    Args:
        *args (Any): Positional arguments for `logging.LogRecord`.
        **kwargs (Any): Keyword arguments for `logging.LogRecord`.

    Returns:
        logging.LogRecord: The record, with `correlation_id` set.
    """
    record = logging.LogRecord(*args, **kwargs)
    record.__dict__["correlation_id"] = correlation_id.get() or "-"
    return record


def one_line(error: BaseException) -> str:
    """Describe an error on a single line, without SQL or its parameters.

    A multi-line message would lose the correlation ID after its first line,
    and SQLAlchemy's full text would put runner IDs in the logs.

    Args:
        error (BaseException): The error to describe.

    Returns:
        str: The database driver's message if there is one, or the error's.
    """
    return " ".join(str(getattr(error, "orig", None) or error).split())


def configure_logging() -> None:
    """Send all logs through one format that names the correlation ID."""
    # A record factory, not a handler filter, so no log line can miss the ID.
    logging.setLogRecordFactory(_make_record)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    for name in ("uvicorn", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.propagate = False
    logging.getLogger("pika").setLevel(logging.WARNING)
