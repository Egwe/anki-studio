"""Reject requests whose ``Host`` header names an unknown host (AS-030).

Only the names in ``allowed_hosts`` of ``studio.yaml`` are accepted. This
blocks DNS rebinding: a foreign web page cannot reach Anki Studio through
a host name that merely resolves to its address.
"""

from collections.abc import Iterable

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

MAX_SHOWN_HOST = 100


def request_host(scope: Scope) -> str:
    """Extract the host name of a request without port and brackets.

    Args:
        scope: ASGI connection scope of an HTTP request.

    Returns:
        The lower-case host name, IPv4 address, or IPv6 address; an empty
        string if the request has no ``Host`` header.
    """
    raw = dict(scope["headers"]).get(b"host", b"").decode("latin-1").strip().lower()
    if raw.startswith("["):
        return raw[1:].partition("]")[0]
    name, colon, port = raw.partition(":")
    if colon and ":" not in port:
        return name
    return raw


class HostCheckMiddleware:
    """Pure ASGI middleware that answers 400 for unknown host names.

    Attributes:
        app: The wrapped ASGI application.
        allowed: Lower-case host names that are accepted.
    """

    def __init__(self, app: ASGIApp, allowed_hosts: Iterable[str]) -> None:
        """Wrap an application with the list of accepted host names.

        Args:
            app: The application to protect.
            allowed_hosts: Accepted host names or IP addresses, without port.
        """
        self.app = app
        self.allowed = frozenset(host.lower() for host in allowed_hosts)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass known hosts through and reject all others.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive channel.
            send: ASGI send channel.

        Returns:
            None.
        """
        if scope["type"] != "http" or request_host(scope) in self.allowed:
            await self.app(scope, receive, send)
            return
        shown = request_host(scope)[:MAX_SHOWN_HOST] or "(leer)"
        response = PlainTextResponse(
            f"Unbekannter Host „{shown}“. Anki Studio antwortet nur auf die Namen "
            "in allowed_hosts der studio.yaml.",
            status_code=400,
        )
        await response(scope, receive, send)
