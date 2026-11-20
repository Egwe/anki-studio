"""Serve login and logout."""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from anki_studio.auth import LOGIN_PATH, SESSION_KEY, safe_next
from anki_studio.credentials import PASSWORD_HASH_ENV
from anki_studio.passwords import verify_password

FAILED_LOGIN_DELAY_SECONDS = 1.0

router = APIRouter()


class LoginForm(BaseModel):
    """Validate the fields of the login form.

    Attributes:
        password: Entered password; at most 1024 characters.
        next: Local path to open after the login.
    """

    password: str = Field(default="", max_length=1024)
    next: str = Field(default="/", max_length=2048)


@router.get(LOGIN_PATH, response_class=HTMLResponse)
def login_page(request: Request, next: str = "/") -> Response:
    """Show the login form, or continue if the session is already logged in.

    Args:
        request: Incoming request.
        next: Local path to open after the login.

    Returns:
        The login page, or a redirect for a logged-in session.
    """
    if request.session.get(SESSION_KEY):
        return RedirectResponse(safe_next(next), status_code=303)
    return _render(request, next=safe_next(next))


@router.post(LOGIN_PATH, response_class=HTMLResponse)
async def login(request: Request, form: Annotated[LoginForm, Form()]) -> Response:
    """Check the password and start a fresh session.

    A wrong password is answered after a fixed delay to slow down guessing.

    Args:
        request: Incoming request with session.
        form: Validated form fields.

    Returns:
        A redirect to ``next`` after success, otherwise the login page with
        status 401 and an error message.
    """
    if await _password_matches(request, form.password):
        request.session.clear()
        request.session[SESSION_KEY] = True
        return RedirectResponse(safe_next(form.next), status_code=303)
    await asyncio.sleep(FAILED_LOGIN_DELAY_SECONDS)
    return _render(
        request, next=safe_next(form.next), error="Das Passwort ist falsch.", status_code=401
    )


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    """End the session.

    Args:
        request: Incoming request with session.

    Returns:
        A redirect to the login page.
    """
    request.session.clear()
    return RedirectResponse(LOGIN_PATH, status_code=303)


async def _password_matches(request: Request, password: str) -> bool:
    """Verify a password against the configured hash off the event loop.

    Args:
        request: Request giving access to the application's credentials.
        password: Entered password.

    Returns:
        False if no password is configured or the password is wrong.
    """
    password_hash = request.app.state.credentials.password_hash
    if password_hash is None:
        return False
    return await run_in_threadpool(verify_password, password, password_hash)


def _render(
    request: Request, *, next: str, error: str | None = None, status_code: int = 200
) -> HTMLResponse:
    """Render the login page.

    Args:
        request: Incoming request.
        next: Local path to open after the login.
        error: Message for a failed attempt, or None.
        status_code: HTTP status of the page.

    Returns:
        The rendered login page.
    """
    context = {
        "next": next,
        "error": error,
        "password_set": request.app.state.credentials.password_hash is not None,
        "hash_env": PASSWORD_HASH_ENV,
    }
    return request.app.state.templates.TemplateResponse(
        request, "login.html", context, status_code=status_code
    )
