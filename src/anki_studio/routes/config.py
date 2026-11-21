"""Show and edit the generator configuration in the interface (AS-009, AS-016)."""

from typing import Any

import yaml
from anki_flashcards.errors import FlashcardError
from anki_flashcards.settings import configuration_diagnostics
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from anki_studio.config_editor import (
    ConfigEditError,
    delete_profile,
    replace_config,
    reset_profile,
    save_defaults,
    save_profile,
)
from anki_studio.generator_config import (
    GeneratorConfig,
    effective_settings,
    load_generator_config,
    profile_views,
    template_config,
)

SOURCE_LABELS = {"built-in": "Standard", "config": "Konfiguration", "cli": "Formular"}
HIDDEN_DIAGNOSTICS = frozenset({"input_file", "output", "json_output", "extend", "sources"})
NOTICES = {
    "defaults": "Standardwerte gespeichert.",
    "profile": "Profil gespeichert.",
    "deleted": "Profil gelöscht.",
    "reset": "Profil auf die Vorlage zurückgesetzt.",
    "upload": "Konfiguration ersetzt.",
}

router = APIRouter()


@router.get("/settings/config", response_class=HTMLResponse)
def config_page(request: Request, saved: str = "") -> HTMLResponse:
    """Show effective values, defaults, profiles, and the file actions.

    Args:
        request: Incoming request.
        saved: Key of ``NOTICES`` after a successful change.

    Returns:
        The configuration page.
    """
    return _render_page(request, notice=NOTICES.get(saved))


@router.post("/settings/config/defaults", response_class=HTMLResponse)
async def save_defaults_route(request: Request) -> Response:
    """Save default profile, generation defaults, and conversion settings.

    Args:
        request: Form submission.

    Returns:
        A redirect with confirmation, or the page with errors (400).
    """
    fields = _text_fields(await request.form())
    try:
        await run_in_threadpool(save_defaults, _path(request), fields)
    except ConfigEditError as error:
        return _render_page(request, errors=error.errors, values=fields, status=400)
    return RedirectResponse("/settings/config?saved=defaults#defaults", status_code=303)


@router.get("/settings/config/profiles/new", response_class=HTMLResponse)
def new_profile(request: Request) -> HTMLResponse:
    """Show an empty profile form.

    Args:
        request: Incoming request.

    Returns:
        The profile editor for a new profile.
    """
    values = {"timeout": "180", "pdf_mode": "local", "image_input": "false"}
    return _render_profile(request, name="", values=values, new=True)


@router.get("/settings/config/profiles/{name}", response_class=HTMLResponse)
def edit_profile(request: Request, name: str) -> HTMLResponse:
    """Show the profile form filled with the stored values.

    Args:
        request: Incoming request.
        name: Profile name.

    Returns:
        The profile editor.

    Raises:
        HTTPException: 404 for unknown profiles.
    """
    profile = _generator(request).config.models.get(name)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profil nicht gefunden")
    values = {
        "model": profile.model,
        "api_base": profile.api_base or "",
        "api_key_env": profile.api_key_env or "",
        "timeout": str(profile.timeout),
        "pdf_mode": profile.pdf_mode.value,
        "image_input": "true" if profile.image_input else "false",
        "options": yaml.safe_dump(profile.options, allow_unicode=True, sort_keys=False)
        if profile.options
        else "",
    }
    return _render_profile(request, name=name, values=values, new=False)


@router.post("/settings/config/profiles/new", response_class=HTMLResponse)
async def create_profile(request: Request) -> Response:
    """Create a profile.

    Args:
        request: Form submission with ``name`` and the profile fields.

    Returns:
        A redirect to the configuration page, or the editor with errors.
    """
    fields = _text_fields(await request.form())
    return await _save_profile(request, fields.get("name", "").strip(), fields, new=True)


@router.post("/settings/config/profiles/{name}", response_class=HTMLResponse)
async def update_profile(request: Request, name: str) -> Response:
    """Replace the values of a profile.

    Args:
        request: Form submission with the profile fields.
        name: Profile name.

    Returns:
        A redirect to the configuration page, or the editor with errors.
    """
    return await _save_profile(request, name, _text_fields(await request.form()), new=False)


@router.post("/settings/config/profiles/{name}/delete", response_class=HTMLResponse)
async def delete_profile_route(request: Request, name: str) -> Response:
    """Delete an own profile that is not in use.

    Args:
        request: Incoming request.
        name: Profile name.

    Returns:
        A redirect with confirmation, or the page with the reason (400).
    """
    standard = set(_template(request).models)
    try:
        await run_in_threadpool(delete_profile, _path(request), name, standard)
    except ConfigEditError as error:
        return _render_page(request, errors=error.errors, status=400)
    return RedirectResponse("/settings/config?saved=deleted#profiles", status_code=303)


@router.post("/settings/config/profiles/{name}/reset", response_class=HTMLResponse)
async def reset_profile_route(request: Request, name: str) -> Response:
    """Reset a standard profile to the template.

    Args:
        request: Incoming request.
        name: Profile name.

    Returns:
        A redirect with confirmation, or the page with the reason (400).
    """
    try:
        await run_in_threadpool(reset_profile, _path(request), name, _template(request))
    except ConfigEditError as error:
        return _render_page(request, errors=error.errors, status=400)
    return RedirectResponse(f"/settings/config?saved=reset#profile-{name}", status_code=303)


@router.get("/settings/config/download")
def download_config(request: Request) -> FileResponse:
    """Download the generator YAML.

    Args:
        request: Incoming request.

    Returns:
        The file as attachment ``generator.yaml``.
    """
    return FileResponse(_path(request), filename="generator.yaml", media_type="application/yaml")


@router.post("/settings/config/upload", response_class=HTMLResponse)
async def upload_config(request: Request) -> Response:
    """Replace the generator YAML with an uploaded, validated file.

    Args:
        request: Multipart form with ``file``.

    Returns:
        A redirect with confirmation, or the page with the reason (400).
    """
    upload = (await request.form()).get("file")
    if not isinstance(upload, UploadFile) or not upload.filename:
        return _render_page(request, errors={"file": "Bitte eine YAML-Datei wählen."}, status=400)
    text = (await upload.read()).decode("utf-8", errors="replace")
    try:
        await run_in_threadpool(replace_config, _path(request), text)
    except ConfigEditError as error:
        return _render_page(request, errors=error.errors, status=400)
    return RedirectResponse("/settings/config?saved=upload", status_code=303)


async def _save_profile(
    request: Request, name: str, fields: dict[str, str], *, new: bool
) -> Response:
    """Save a profile and answer with a redirect or the editor with errors.

    Args:
        request: Incoming request.
        name: Profile name.
        fields: Entered values.
        new: Whether the profile is created.

    Returns:
        The response.
    """
    try:
        await run_in_threadpool(save_profile, _path(request), name, fields, new=new)
    except ConfigEditError as error:
        return _render_profile(
            request, name=name, values=fields, new=new, errors=error.errors, status=400
        )
    return RedirectResponse(f"/settings/config?saved=profile#profile-{name}", status_code=303)


def _text_fields(data: Any) -> dict[str, str]:
    """Collect text fields; the last value of a name wins (hidden ``false`` first).

    Args:
        data: Parsed form.

    Returns:
        Field name to text value.
    """
    return {name: str(data.getlist(name)[-1]) for name in data.keys()}


def _path(request: Request) -> Any:
    """Return the generator YAML of the application.

    Args:
        request: Incoming request.

    Returns:
        The path from the settings.
    """
    return request.app.state.settings.generator_path


def _generator(request: Request) -> GeneratorConfig:
    """Load the generator YAML or answer with a 500 page explaining it.

    Args:
        request: Incoming request.

    Returns:
        The loaded configuration.

    Raises:
        HTTPException: 500 if the file cannot be loaded.
    """
    try:
        return load_generator_config(_path(request))
    except FlashcardError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error


def _template(request: Request) -> Any:
    """Return the bundled template configuration.

    Args:
        request: Incoming request.

    Returns:
        The template as ``AppConfig``.
    """
    return template_config(request.app.state.settings.data_dir / "models")


def _diagnostics(generator: GeneratorConfig) -> list[tuple[str, str, str]]:
    """Describe the effective values with their source, without secrets.

    Args:
        generator: Loaded configuration.

    Returns:
        Rows of name, value, and German source label; structured PDF values
        are prefixed with ``pdf_conversion.``.
    """
    try:
        data = configuration_diagnostics(effective_settings(generator, {}), generator.path)
    except FlashcardError as error:
        return [("Fehler", str(error), "")]
    sources = data["sources"]
    rows = [
        (name, str(value), SOURCE_LABELS.get(sources.get(name, ""), ""))
        for name, value in data.items()
        if name not in HIDDEN_DIAGNOSTICS and not isinstance(value, dict)
    ]
    conversion = data.get("pdf_conversion", {})
    rows += [(f"pdf_conversion.{name}", str(value), "") for name, value in conversion.items()]
    return rows


def _default_fields(config: Any) -> dict[str, str]:
    """Fill the defaults form from the stored configuration.

    Args:
        config: Loaded ``AppConfig``.

    Returns:
        Form field name to text value; unset values are empty.
    """
    generation = config.generation
    conversion = config.pdf_conversion
    pictures = conversion.pictures
    values: dict[str, Any] = {
        "default_profile": config.default_profile or generation.profile,
        "generation.deck": generation.deck,
        "generation.limit": generation.limit,
        "generation.language": generation.language,
        "generation.instructions": generation.instructions,
        "generation.chunk_size": generation.chunk_size,
        "generation.timeout": generation.timeout,
        "generation.pdf_mode": generation.pdf_mode,
        "generation.subdecks": generation.subdecks,
        "pdf_conversion.ocr_languages": " ".join(conversion.ocr_languages),
        "pdf_conversion.force_ocr": conversion.force_ocr,
        "pdf_conversion.formulas": conversion.formulas,
        "pdf_conversion.allow_unreadable": conversion.allow_unreadable,
        "pdf_conversion.allow_cpu": conversion.allow_cpu,
        "pdf_conversion.formula_batch_size": conversion.formula_batch_size,
        "pictures.backend": pictures.backend,
        "pictures.model": pictures.model,
        "pictures.profile": pictures.profile,
    }
    return {name: _text(value) for name, value in values.items()}


def _text(value: Any) -> str:
    """Turn a configuration value into form text.

    Args:
        value: Value of the configuration.

    Returns:
        ``""`` for None, ``true``/``false`` for booleans, the enum value or
        the string otherwise.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(getattr(value, "value", value))


def _render_page(
    request: Request,
    *,
    notice: str | None = None,
    errors: dict[str, str] | None = None,
    values: dict[str, str] | None = None,
    status: int = 200,
) -> HTMLResponse:
    """Render the configuration page.

    Args:
        request: Incoming request.
        notice: Confirmation, or None.
        errors: Field name to message.
        values: Entered default values after an error, or None.
        status: HTTP status.

    Returns:
        The rendered page.
    """
    generator = _generator(request)
    config = generator.config
    context = {
        "notice": notice,
        "errors": errors or {},
        "values": values or _default_fields(config),
        "config": config,
        "path": str(generator.path),
        "diagnostics": _diagnostics(generator),
        "profiles": profile_views(generator),
        "standard": set(_template(request).models),
    }
    return request.app.state.templates.TemplateResponse(
        request, "config.html", context, status_code=status
    )


def _render_profile(
    request: Request,
    *,
    name: str,
    values: dict[str, str],
    new: bool,
    errors: dict[str, str] | None = None,
    status: int = 200,
) -> HTMLResponse:
    """Render the profile editor.

    Args:
        request: Incoming request.
        name: Profile name (empty for a new profile).
        values: Field values to show.
        new: Whether a profile is created.
        errors: Field name to message.
        status: HTTP status.

    Returns:
        The rendered editor.
    """
    context = {"name": name, "values": values, "new": new, "errors": errors or {}}
    return request.app.state.templates.TemplateResponse(
        request, "config_profile.html", context, status_code=status
    )
