"""Refuse oversized requests before their body is read (AS-033).

Uploads are parsed by Starlette into temporary files. To keep that bounded,
every POST must announce its size with ``Content-Length``; requests above
the limit of their path are answered with 413 before any byte is read.
uvicorn rejects bodies longer than the announced length.
"""

from collections.abc import Mapping

from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from anki_studio.uploads import APKG, CARD_JSON, DOCUMENT

MAX_DOCUMENTS = 10
FORM_OVERHEAD = 2**20
DEFAULT_LIMIT = 2**20
UPLOAD_LIMIT = MAX_DOCUMENTS * DOCUMENT.max_size + APKG.max_size + FORM_OVERHEAD
PATH_LIMITS = {
    "/decks": APKG.max_size + FORM_OVERHEAD,
    "/export": CARD_JSON.max_size + FORM_OVERHEAD,
    "/generate": UPLOAD_LIMIT,
}


class BodyLimitMiddleware:
    """Pure ASGI middleware that checks ``Content-Length`` of POST requests.

    Attributes:
        app: The wrapped ASGI application.
        limits: Maximum body size in bytes per path.
        default: Maximum body size of all other POST requests.
    """

    def __init__(
        self, app: ASGIApp, limits: Mapping[str, int] | None = None, default: int = DEFAULT_LIMIT
    ) -> None:
        """Wrap an application with body size limits.

        Args:
            app: The application to protect.
            limits: Maximum body size per path; None uses ``PATH_LIMITS``.
            default: Maximum body size of other POST requests.
        """
        self.app = app
        self.limits = dict(PATH_LIMITS if limits is None else limits)
        self.default = default

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass small or bodiless requests and refuse the others.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive channel.
            send: ASGI send channel.

        Returns:
            None.
        """
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return
        response = self._refusal(scope)
        if response is None:
            await self.app(scope, receive, send)
            return
        await response(scope, receive, send)

    def _refusal(self, scope: Scope) -> PlainTextResponse | None:
        """Decide whether a POST request is refused.

        Args:
            scope: ASGI scope of a POST request.

        Returns:
            411 without a valid ``Content-Length``, 413 above the limit,
            otherwise None.
        """
        announced = dict(scope["headers"]).get(b"content-length", b"").decode("latin-1")
        if not announced.isdigit():
            return PlainTextResponse("Die Anfrage braucht eine Längenangabe.", status_code=411)
        limit = self.limits.get(scope["path"], self.default)
        if int(announced) > limit:
            megabytes = limit // 2**20
            return PlainTextResponse(
                f"Die Anfrage ist größer als {megabytes} MiB.", status_code=413
            )
        return None
