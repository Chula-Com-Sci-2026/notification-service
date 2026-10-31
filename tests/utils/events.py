import uuid
from datetime import UTC, datetime
from typing import Any


def make_event(
    event_type: str = "BuddyRequestSent",
    *,
    sender_id: uuid.UUID | None = None,
    recipient_id: uuid.UUID | None = None,
    status: str | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Build a valid buddy event as a publisher would send it.

    Args:
        event_type (str, optional): The event type. Defaults to
            "BuddyRequestSent".
        sender_id (uuid.UUID, optional): Sender. Defaults to a new ID.
        recipient_id (uuid.UUID, optional): Recipient. Defaults to a new ID.
        status (str, optional): Payload status. Defaults to the first status
            the event type allows.
        **overrides (Any): Envelope fields to replace.

    Returns:
        dict[str, Any]: The event, ready to encode as JSON.
    """
    default_status = "pending" if event_type == "BuddyRequestSent" else "accepted"
    return {
        "eventId": str(uuid.uuid4()),
        "eventType": event_type,
        "version": 1,
        "occurredAt": datetime.now(UTC).isoformat(),
        "correlationId": str(uuid.uuid4()),
        "payload": {
            "requestId": str(uuid.uuid4()),
            "senderId": str(sender_id or uuid.uuid4()),
            "recipientId": str(recipient_id or uuid.uuid4()),
            "status": status or default_status,
        },
    } | overrides
