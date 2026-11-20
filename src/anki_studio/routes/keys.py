"""Set, replace, and delete provider API keys in the interface (AS-035).

The pages never contain a key value; after saving only the variable name
and its status are shown.
"""

from typing import Annotated, Any

from anki_flashcards.errors import FlashcardError
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from anki_studio.generator_config import load_generator_config
from anki_studio.secret_store import SecretStoreError, valid_name

router = APIRouter()


class KeyForm(BaseModel):
    """Hold the submitted key; it is validated by the secret store.

    Attributes:
        value: The new API key.
    """

    value: str = ""


@router.get("/settings/keys", response_class=HTMLResponse)
def keys_page(request: Request, saved: str = "", deleted: str = "") -> HTMLResponse:
    """List the key variables of all profiles with their status.

    Args:
        request: Incoming request.
        saved: Variable that was just stored, for a confirmation.
        deleted: Variable that was just deleted, for a confirmation.

    Returns:
        The rendered page.
    """
    notice = _notice(saved, "gespeichert") or _notice(deleted, "gelöscht")
    return _render(request, notice=notice)


@router.post("/settings/keys/{name}", response_class=HTMLResponse)
async def set_key(request: Request, name: str, form: Annotated[KeyForm, Form()]) -> Response:
    """Store or replace one key.

    Args:
        request: Incoming request.
        name: Variable from the URL.
        form: Submitted value.

    Returns:
        A redirect with confirmation, or the page with an error (400).
    """
    try:
        await run_in_threadpool(request.app.state.secrets.set, name, form.value)
    except SecretStoreError as error:
        return _render(request, errors={name: str(error)}, status=400)
    return RedirectResponse(f"/settings/keys?saved={name}#{name}", status_code=303)


@router.post("/settings/keys/{name}/delete", response_class=HTMLResponse)
async def delete_key(request: Request, name: str) -> Response:
    """Delete one stored key.

    Args:
        request: Incoming request.
        name: Variable from the URL.

    Returns:
        A redirect with confirmation, or the page with an error (400).
    """
    try:
        await run_in_threadpool(request.app.state.secrets.delete, name)
    except SecretStoreError as error:
        return _render(request, errors={name: str(error)}, status=400)
    return RedirectResponse(f"/settings/keys?deleted={name}#{name}", status_code=303)


def _notice(name: str, action: str) -> str | None:
    """Build a confirmation for a valid variable name only.

    Args:
        name: Name from the query string.
        action: ``gespeichert`` or ``gelöscht``.

    Returns:
        The message, or None for an empty or invalid name.
    """
    return f"Schlüssel {name} {action}." if valid_name(name) else None


def _profiles_by_variable(request: Request) -> tuple[dict[str, list[str]], str | None]:
    """Group the profiles of the generator YAML by their key variable.

    Args:
        request: Incoming request; gives access to the settings.

    Returns:
        Variable name to profile names, and an error message if the YAML
        cannot be loaded.
    """
    try:
        generator = load_generator_config(request.app.state.settings.generator_path)
    except FlashcardError as error:
        return {}, str(error)
    groups: dict[str, list[str]] = {}
    for name, profile in generator.config.models.items():
        if profile.api_key_env:
            groups.setdefault(profile.api_key_env, []).append(name)
    return groups, None


def _render(
    request: Request,
    *,
    notice: str | None = None,
    errors: dict[str, str] | None = None,
    status: int = 200,
) -> HTMLResponse:
    """Render the key page.

    Args:
        request: Incoming request.
        notice: Confirmation to show, or None.
        errors: Variable name to error message.
        status: HTTP status of the page.

    Returns:
        The rendered page without any key value.
    """
    store = request.app.state.secrets
    profiles, config_error = _profiles_by_variable(request)
    context: dict[str, Any] = {
        "notice": notice,
        "errors": errors or {},
        "available": store.available,
        "store_error": request.app.state.secrets_error,
        "config_error": config_error,
        "profiles": profiles,
        "rows": [],
    }
    try:
        context["rows"] = store.status(profiles)
    except SecretStoreError as error:
        context["store_error"] = str(error)
    return request.app.state.templates.TemplateResponse(
        request, "keys.html", context, status_code=status
    )
