"""Require a login for every page except the login page, static files, and health check.

The session itself is Starlette's signed session cookie (``HttpOnly``,
``SameSite=Strict``); this module only decides which requests need it and
where an anonymous request is sent (AS-030).
"""

from urllib.parse import urlencode

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

SESSION_KEY = "authenticated"
SESSION_COOKIE = "anki_studio_session"
SESSION_MAX_AGE = 14 * 24 * 60 * 60
LOGIN_PATH = "/login"
PUBLIC_PATHS = frozenset({LOGIN_PATH, "/language", "/healthz"})
PUBLIC_PREFIXES = ("/static/",)


def is_public(path: str) -> bool:
    """Tell whether a path is reachable without login.

    Args:
        path: Request path without query string.

    Returns:
        True for the login page, the health check, and static files.
    """
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


def safe_next(target: str | None) -> str:
    """Return a local path to open after the login.

    Args:
        target: Requested path, possibly with query string, or None.

    Returns:
        ``target`` if it is a local path other than the login page;
        otherwise ``/``. Absolute and scheme-relative URLs are refused.
    """
    if not target or not target.startswith("/") or target.startswith(("//", "/\\")):
        return "/"
    if target == LOGIN_PATH or target.startswith(LOGIN_PATH + "?"):
        return "/"
    return target


def login_location(request: Request) -> str:
    """Build the login URL that leads back to the requested page.

    Args:
        request: Anonymous request for a protected page.

    Returns:
        ``/login`` for the start page and non-GET requests, otherwise
        ``/login?next=<path and query>``.
    """
    target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    if request.method != "GET" or target == "/":
        return LOGIN_PATH
    return f"{LOGIN_PATH}?{urlencode({'next': target})}"


class LoginRequiredMiddleware:
    """Pure ASGI middleware that sends anonymous requests to the login page.

    It must run inside Starlette's ``SessionMiddleware``. htmx requests get
    status 401 with an ``HX-Redirect`` header so the whole page changes.

    Attributes:
        app: The wrapped ASGI application.
    """

    def __init__(self, app: ASGIApp) -> None:
        """Wrap an application.

        Args:
            app: The application to protect.
        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass public or logged-in requests through and redirect all others.

        Args:
            scope: ASGI connection scope; ``scope["session"]`` is set by the
                session middleware.
            receive: ASGI receive channel.
            send: ASGI send channel.

        Returns:
            None.
        """
        if scope["type"] != "http" or is_public(scope["path"]) or _logged_in(scope):
            await self.app(scope, receive, send)
            return
        await _login_response(Request(scope))(scope, receive, send)


def _logged_in(scope: Scope) -> bool:
    """Read the login flag from the session.

    Args:
        scope: ASGI scope with the decoded session.

    Returns:
        True if the session belongs to a successful login.
    """
    return bool(scope.get("session", {}).get(SESSION_KEY))


def _login_response(request: Request) -> Response:
    """Answer an anonymous request for a protected page.

    Args:
        request: The anonymous request.

    Returns:
        401 with ``HX-Redirect`` for htmx, otherwise a 303 redirect.
    """
    if request.headers.get("hx-request") == "true":
        return Response(status_code=401, headers={"HX-Redirect": LOGIN_PATH})
    return RedirectResponse(login_location(request), status_code=303)
