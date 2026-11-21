"""Store the interface language selected in the navigation."""

from typing import Annotated, Literal

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from anki_studio.i18n import SESSION_LOCALE

router = APIRouter()


class LanguageForm(BaseModel):
    """Validate the language selection form.

    Attributes:
        locale: One of the interface languages bundled with the application.
        next: Local path to redisplay after changing the language.
    """

    locale: Literal["en", "de"]
    next: str = Field(default="/", max_length=2048)


@router.post("/language")
def set_language(request: Request, form: Annotated[LanguageForm, Form()]) -> RedirectResponse:
    """Persist a selected interface language in the signed session.

    Args:
        request: Incoming request whose session is updated.
        form: Validated language code and return location.

    Returns:
        A 303 redirect to the safe local return location.
    """
    request.session[SESSION_LOCALE] = form.locale
    return RedirectResponse(_local_path(form.next), status_code=303)


def _local_path(target: str) -> str:
    """Return a safe local redirect target, including the login page.

    Args:
        target: Form-provided path, potentially hostile or absolute.

    Returns:
        ``target`` if it begins with one safe slash, otherwise ``/``.
    """
    if not target.startswith("/") or target.startswith(("//", "/\\")):
        return "/"
    return target
