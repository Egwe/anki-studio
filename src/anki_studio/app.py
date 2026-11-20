"""Create the FastAPI application of Anki Studio."""

import logging
import os

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from anki_studio.auth import SESSION_COOKIE, SESSION_MAX_AGE, LoginRequiredMiddleware
from anki_studio.credentials import SESSION_SECRET_ENV, Credentials, load_credentials
from anki_studio.headers import SecurityHeadersMiddleware
from anki_studio.hosts import HostCheckMiddleware
from anki_studio.routes import login, pages
from anki_studio.settings import StudioSettings
from anki_studio.templating import STATIC_DIR, create_templates

logger = logging.getLogger(__name__)


def create_app(
    settings: StudioSettings | None = None, credentials: Credentials | None = None
) -> FastAPI:
    """Build the web application with routes, static files, and middleware.

    Middleware from the outside in: security headers, host check, signed
    session cookie, login requirement. The interactive API documentation is
    disabled: it would load scripts from a CDN and is not needed.

    Args:
        settings: Validated settings; None uses the built-in defaults.
        credentials: Login secrets; None reads them from ``os.environ``.

    Returns:
        A configured application; ``app.state`` holds ``settings``,
        ``credentials``, and ``templates``.

    Raises:
        CredentialsError: If ``credentials`` is None and the environment
            holds an invalid password hash or session key.
    """
    settings = settings or StudioSettings()
    credentials = credentials or load_credentials(os.environ)
    if credentials.temporary_secret:
        logger.warning(
            "%s fehlt: zufälliger Session-Schlüssel, Anmeldungen enden mit einem Neustart.",
            SESSION_SECRET_ENV,
        )
    app = FastAPI(title="Anki Studio", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.credentials = credentials
    app.state.templates = create_templates()
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(login.router)
    app.include_router(pages.router)
    app.add_middleware(LoginRequiredMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=credentials.session_secret,
        session_cookie=SESSION_COOKIE,
        max_age=SESSION_MAX_AGE,
        same_site="strict",
    )
    app.add_middleware(HostCheckMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(SecurityHeadersMiddleware)
    return app
