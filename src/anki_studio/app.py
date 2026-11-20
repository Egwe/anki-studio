"""Create the FastAPI application of Anki Studio."""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from anki_studio.headers import SecurityHeadersMiddleware
from anki_studio.routes import pages
from anki_studio.settings import StudioSettings
from anki_studio.templating import STATIC_DIR, create_templates


def create_app(settings: StudioSettings | None = None) -> FastAPI:
    """Build the web application with routes, static files, and middleware.

    The interactive API documentation is disabled: it would load scripts
    from a CDN and is not needed by the single user.

    Args:
        settings: Validated settings; None uses the built-in defaults.

    Returns:
        A configured application; ``app.state.settings`` holds the settings
        and ``app.state.templates`` the template renderer.
    """
    app = FastAPI(title="Anki Studio", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings or StudioSettings()
    app.state.templates = create_templates()
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(pages.router)
    app.add_middleware(SecurityHeadersMiddleware)
    return app
