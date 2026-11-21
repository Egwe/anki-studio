"""Change login and sync access settings without shell access (AS-016)."""

import secrets
from typing import Annotated, Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from anki_studio.credentials import Credentials
from anki_studio.passwords import hash_password, verify_password
from anki_studio.runtime_env import RuntimeEnvironment, RuntimeEnvironmentError
from anki_studio.settings import validate_sync_endpoint

router = APIRouter()


class PasswordForm(BaseModel):
    """Validate a replacement login password before hashing it.

    Attributes:
        current: Current login password; proves that the person at the
            browser knows it, not only holds a session.
        password: New plain-text password with at most 1024 characters.
        confirmation: Repeated plain-text password.
    """

    current: str = Field(default="", max_length=1024)
    password: str = Field(default="", max_length=1024)
    confirmation: str = Field(default="", max_length=1024)


class SyncAccessForm(BaseModel):
    """Validate daily sync access input before storing it in the environment.

    Attributes:
        enabled: Whether synchronization should be configured.
        endpoint: HTTP(S) endpoint without embedded credentials.
        username: Account name on the configured sync server.
        password: Plain-text password for ``username``; never rendered again.
            Empty keeps the stored password as long as the user name stays.
    """

    enabled: bool = False
    endpoint: str = Field(default="", max_length=500)
    username: str = Field(default="", max_length=1024)
    password: str = Field(default="", max_length=1024)


@router.get("/settings/access", response_class=HTMLResponse)
def access_page(request: Request) -> HTMLResponse:
    """Show forms for login and sync access without rendering passwords.

    Args:
        request: Authenticated browser request.

    Returns:
        The access settings page.
    """
    return _render(request)


@router.post("/settings/access/password", response_class=HTMLResponse)
async def change_password(request: Request, form: Annotated[PasswordForm, Form()]) -> Response:
    """Store a new login hash and rotate the session signing secret.

    Args:
        request: Authenticated browser request.
        form: Current password, new password and its confirmation.

    Returns:
        A redirect while the service restarts, or the form with an error.
    """
    credentials = request.app.state.credentials
    if not await run_in_threadpool(_current_password_matches, credentials, form.current):
        return _render(request, password_error="Das aktuelle Passwort ist falsch.", status=400)
    if form.password != form.confirmation:
        return _render(
            request,
            password_error="Die beiden Passwörter stimmen nicht überein.",
            status=400,
        )
    try:
        password_hash = await run_in_threadpool(hash_password, form.password)
    except ValueError as error:
        return _render(request, password_error=str(error), status=400)
    try:
        await run_in_threadpool(
            _runtime(request).save,
            password_hash=password_hash,
            session_secret=secrets.token_urlsafe(48),
            sync_endpoint=request.app.state.settings.sync_endpoint,
            sync_username=credentials.sync_username,
            sync_password=credentials.sync_password,
        )
    except RuntimeEnvironmentError as error:
        return _render(request, password_error=str(error), status=500)
    except OSError:
        return _render(
            request,
            password_error="Die Zugangsdaten konnten nicht sicher gespeichert werden.",
            status=500,
        )
    return _restart_response(request)


@router.post("/settings/access/sync", response_class=HTMLResponse)
async def change_sync_access(request: Request, form: Annotated[SyncAccessForm, Form()]) -> Response:
    """Replace or disable the complete sync connection setup.

    Args:
        request: Authenticated browser request.
        form: Sync activation flag and connection values.

    Returns:
        A redirect while the service restarts, or the form with an error.
    """
    credentials = request.app.state.credentials
    values, error = _sync_values(form, credentials)
    if error is not None:
        return _render(request, sync_error=error, sync_values=form, status=400)
    endpoint, username, password = values
    try:
        await run_in_threadpool(
            _runtime(request).save,
            password_hash=credentials.password_hash,
            session_secret=credentials.session_secret,
            sync_endpoint=endpoint,
            sync_username=username,
            sync_password=password,
        )
    except RuntimeEnvironmentError as error:
        return _render(request, sync_error=str(error), sync_values=form, status=500)
    except OSError:
        return _render(
            request,
            sync_error="Die Sync-Zugangsdaten konnten nicht sicher gespeichert werden.",
            sync_values=form,
            status=500,
        )
    return _restart_response(request)


def _current_password_matches(credentials: Credentials, password: str) -> bool:
    """Check the current login password before it may be replaced.

    Args:
        credentials: Loaded credentials of the running service.
        password: Password entered in the form.

    Returns:
        True if a login hash exists and ``password`` matches it.
    """
    if credentials.password_hash is None:
        return False
    return verify_password(password, credentials.password_hash)


def _sync_values(
    form: SyncAccessForm, credentials: Credentials
) -> tuple[tuple[str | None, str | None, str | None], str | None]:
    """Validate a complete enabled connection or an explicit disabled state.

    An empty password field keeps the stored password while the user name
    stays the same, so changing only the endpoint needs no retyping.

    Args:
        form: Submitted sync form.
        credentials: Currently loaded sync credentials.

    Returns:
        Endpoint, user name, and password together with an error.  The three
        values are all None when synchronization is disabled.
    """
    if not form.enabled:
        return (None, None, None), None
    username = form.username.strip()
    password = form.password
    if not password and username == credentials.sync_username:
        password = credentials.sync_password or ""
    if not username or not password:
        return (None, None, None), "Benutzername und Passwort sind erforderlich."
    try:
        endpoint = validate_sync_endpoint(form.endpoint)
    except ValueError as error:
        return (None, None, None), f"Sync-Endpunkt {error}"
    return (endpoint, username, password), None


def _runtime(request: Request) -> RuntimeEnvironment:
    """Return the private runtime environment associated with this app.

    Args:
        request: Incoming request giving access to application settings.

    Returns:
        The file writer below the configured data directory, encrypting with
        the configured ``ANKI_STUDIO_SECRET_KEY``.
    """
    return RuntimeEnvironment(
        request.app.state.settings.data_dir, request.app.state.credentials.secret_key
    )


def _restart_response(request: Request) -> RedirectResponse:
    """Return a response that asks the service to restart after delivery.

    Args:
        request: Incoming request whose app provides ``request_restart``.

    Returns:
        Redirect to the login page; a rotated session must be authenticated
        again and a stable URL avoids resubmitting the form on refresh.
    """
    response = RedirectResponse("/login?changed=1", status_code=303)
    response.background = BackgroundTask(request.app.state.request_restart)
    return response


def _render(
    request: Request,
    *,
    password_error: str | None = None,
    sync_error: str | None = None,
    sync_values: SyncAccessForm | None = None,
    status: int = 200,
) -> HTMLResponse:
    """Render the access page with safe values and optional form errors.

    Args:
        request: Incoming request.
        password_error: Password form error, if any.
        sync_error: Sync form error, if any.
        sync_values: Submitted non-secret sync fields for redisplay.
        status: HTTP status of the page.

    Returns:
        The rendered settings page.
    """
    settings = request.app.state.settings
    credentials = request.app.state.credentials
    values = sync_values or SyncAccessForm(
        enabled=bool(
            settings.sync_endpoint and credentials.sync_username and credentials.sync_password
        ),
        endpoint=settings.sync_endpoint or "",
        username=credentials.sync_username or "",
    )
    context: dict[str, Any] = {
        "password_error": password_error,
        "sync_error": sync_error,
        "sync_values": values,
        "sync_password_set": credentials.sync_password is not None,
    }
    return request.app.state.templates.TemplateResponse(
        request, "access.html", context, status_code=status
    )
