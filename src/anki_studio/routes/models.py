"""Show the models a profile's provider offers (AS-014).

The answer is an HTML fragment for htmx: a selection for the generation
form or a short check result for the key page.
"""

import os

from anki_flashcards.config import ModelProfile
from anki_flashcards.errors import FlashcardError
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from anki_studio.forms import error_message
from anki_studio.generator_config import load_generator_config
from anki_studio.model_catalog import ModelList, ModelListError, list_models

router = APIRouter()


@router.get("/models", response_class=HTMLResponse)
async def model_list(
    request: Request,
    profile: str = "",
    view: str = "form",
    model: str = "",
    api_base: str = "",
    api_key_env: str = "",
) -> HTMLResponse:
    """Load the models of a profile's provider and render them.

    Args:
        request: Incoming request.
        profile: Profile name; empty selects the default profile.
        view: ``form`` for a selection, ``keys`` for a check result.
        model: Provider and model of an unsaved profile, used when no
            profile name is given (profile editor).
        api_base: Endpoint of the unsaved profile, or empty.
        api_key_env: Key variable of the unsaved profile, or empty.

    Returns:
        The fragment with the models or a German error message.
    """
    result: ModelList | None = None
    error: str | None = None
    try:
        selected = (
            _unsaved_profile(model, api_base, api_key_env)
            if model and not profile
            else _profile(request, profile)
        )
        result = await run_in_threadpool(
            list_models, selected, os.environ, request.app.state.http_transport
        )
    except (FlashcardError, ModelListError) as problem:
        error = str(problem)
    except ValidationError as problem:
        error = "; ".join(error_message(item) for item in problem.errors())
    template = "_model_check.html" if view == "keys" else "_model_list.html"
    context = {"result": result, "error": error}
    return request.app.state.templates.TemplateResponse(request, template, context)


def _unsaved_profile(model: str, api_base: str, api_key_env: str) -> ModelProfile:
    """Build a profile from the fields of the profile editor.

    Args:
        model: Provider and model.
        api_base: Endpoint, or empty.
        api_key_env: Key variable, or empty.

    Returns:
        A validated profile.

    Raises:
        ValidationError: If the generator's schema refuses the values.
    """
    return ModelProfile.model_validate(
        {
            "model": model.strip(),
            "api_base": api_base.strip() or None,
            "api_key_env": api_key_env.strip() or None,
        }
    )


def _profile(request: Request, name: str) -> ModelProfile:
    """Find a profile of the generator YAML.

    Args:
        request: Incoming request; gives access to the settings.
        name: Profile name; empty selects the default profile.

    Returns:
        The profile.

    Raises:
        FlashcardError: If the YAML cannot be loaded or no such profile exists.
    """
    config = load_generator_config(request.app.state.settings.generator_path).config
    selected = name or config.selected_profile_name()
    if not selected or selected not in config.models:
        raise FlashcardError(f"Profil „{selected or '(keins)'}“ gibt es nicht.")
    return config.models[selected]
