"""Format Server-Sent Events for the live job page (AS-004)."""

KEEPALIVE = ": keepalive\n\n"


def sse_message(event: str, data: str, event_id: int | None = None) -> str:
    """Format one Server-Sent Event.

    Args:
        event: Event name the browser listens to, for example ``line``.
        data: Payload; every line becomes its own ``data:`` field.
        event_id: Optional id the browser sends back as ``Last-Event-ID``
            after a reconnect.

    Returns:
        The event text ending with a blank line.
    """
    fields = [f"event: {event}"]
    if event_id is not None:
        fields.append(f"id: {event_id}")
    fields += [f"data: {line}" for line in data.splitlines() or [""]]
    return "\n".join(fields) + "\n\n"
