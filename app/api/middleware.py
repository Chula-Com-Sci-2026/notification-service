import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logs import correlation_id

CORRELATION_HEADER = "X-Correlation-Id"


def _resolve_correlation_id(value: str | None) -> str:
    """Return the caller's correlation ID, or a new one if it is unusable.

    Only a UUID is kept, matching the event envelope. That also stops a
    caller from writing arbitrary text into the logs.

    Args:
        value (str | None): Header value from the request.

    Returns:
        str: A normalized UUID string.
    """
    try:
        return str(uuid.UUID(value))
    except TypeError, ValueError:
        return str(uuid.uuid4())


class CorrelationIdMiddleware:
    """Tag each request's logs and response with a correlation ID (NFR-7.4)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle one ASGI connection.

        Args:
            scope (Scope): Connection details.
            receive (Receive): Channel for incoming messages.
            send (Send): Channel for outgoing messages.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        value = _resolve_correlation_id(Headers(scope=scope).get(CORRELATION_HEADER))
        # Not reset: each request has its own task, and uvicorn's error log for
        # a crash runs after the app returns but must still name this ID.
        correlation_id.set(value)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[CORRELATION_HEADER] = value
            await send(message)

        await self.app(scope, receive, send_with_header)
