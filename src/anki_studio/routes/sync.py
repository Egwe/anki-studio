"""Show synchronization status and submit safe sync jobs (AS-011)."""

from anki_flashcards.errors import FlashcardError
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from anki_studio.sync import SYNC_KIND, SYNC_TITLE, SyncState

router = APIRouter()


@router.get("/sync", response_class=HTMLResponse)
def sync_page(request: Request) -> HTMLResponse:
    """Show current non-secret synchronization status.

    Args:
        request: Incoming request with the configured sync service.

    Returns:
        Status page with setup state, last result, and sync action.
    """
    return _render(request)


@router.post("/sync")
def sync_submit(request: Request) -> Response:
    """Create one no-upload synchronization job.

    Args:
        request: Incoming request with job store, worker, and sync service.

    Returns:
        Redirect to the live job page, or status page when setup is missing.
    """
    service = request.app.state.sync_service
    if not service.configured:
        return _render(request, error="Sync ist noch nicht vollständig eingerichtet.", status=400)
    job = request.app.state.jobs.create_task(SYNC_TITLE, {"kind": SYNC_KIND})
    request.app.state.worker.submit(job)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


def _render(request: Request, *, error: str | None = None, status: int = 200) -> HTMLResponse:
    """Render status with only safe configuration and state fields.

    Args:
        request: Incoming request with settings and credentials.
        error: Curated status-read or setup error, if any.
        status: HTTP response status.

    Returns:
        Rendered status page.
    """
    try:
        sync_state = request.app.state.sync_service.state()
    except FlashcardError as state_error:
        sync_state = SyncState()
        error = error or str(state_error)
    settings = request.app.state.settings
    credentials = request.app.state.credentials
    context = {
        "state": sync_state,
        "configured": request.app.state.sync_service.configured,
        "endpoint": sync_state.redirect_endpoint or settings.sync_endpoint,
        "username": credentials.sync_username,
        "password_set": credentials.sync_password is not None,
        "error": error,
    }
    return request.app.state.templates.TemplateResponse(
        request, "sync.html", context, status_code=status
    )
