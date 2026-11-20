"""Serve the start page and the health check."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def start_page(request: Request) -> HTMLResponse:
    """Render the start page.

    Args:
        request: Incoming request; gives access to the templates.

    Returns:
        The rendered start page.
    """
    return request.app.state.templates.TemplateResponse(request, "start.html")


@router.get("/healthz")
def health() -> dict[str, str]:
    """Report that the process answers requests.

    Returns:
        ``{"status": "ok"}``; used by deployment checks.
    """
    return {"status": "ok"}
