"""Add security headers to every HTTP response.

The Content Security Policy only allows resources from Anki Studio itself,
so the browser blocks any external script, style, font, or connection
(AS-012). Alpine.js needs ``'unsafe-eval'`` for its expressions; inline
scripts and inline style elements stay forbidden.
"""

from starlette.types import ASGIApp, Message, Receive, Scope, Send

CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self' 'unsafe-eval'",
        "style-src 'self'",
        "img-src 'self' data:",
        "connect-src 'self'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    )
)

SECURITY_HEADERS = (
    (b"content-security-policy", CONTENT_SECURITY_POLICY.encode()),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
)


class SecurityHeadersMiddleware:
    """Pure ASGI middleware that appends the security headers.

    It wraps ``send`` instead of buffering responses, so streamed responses
    such as Server-Sent Events pass through unchanged.

    Attributes:
        app: The wrapped ASGI application.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap an ASGI application.

        Args:
            app: The application whose responses receive the headers.
        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Forward a request and add the headers to HTTP response starts.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive channel.
            send: ASGI send channel of the server.

        Returns:
            None.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            """Append the security headers to the response start message.

            Args:
                message: ASGI message sent by the application.

            Returns:
                None.
            """
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), *SECURITY_HEADERS]
            await send(message)

        await self.app(scope, receive, send_with_headers)
