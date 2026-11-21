"""Export an uploaded generator card JSON file to a new APKG (AS-008, APKG part)."""

from typing import Any

from anki_flashcards.errors import FlashcardError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, UploadFile

from anki_studio.card_export import EXPORT_FILE, EXPORT_KIND
from anki_studio.forms import ExportForm, ExportTarget, form_errors
from anki_studio.generator_config import load_generator_config
from anki_studio.i18n import locale_from_request, translate_request
from anki_studio.jobs import Job, JobStatus, JobStore
from anki_studio.uploads import CARD_JSON, UploadError, check_upload, clean_filename
from anki_studio.worker import JobWorker

router = APIRouter()


@router.get("/export", response_class=HTMLResponse)
def export_page(request: Request) -> HTMLResponse:
    """Show the card-JSON export form.

    Args:
        request: Incoming request.

    Returns:
        The form with the generator's configured default deck, if available.
    """
    return _render(request, values={}, errors={})


@router.post("/export", response_class=HTMLResponse)
async def export_submit(request: Request) -> Response:
    """Validate a card-JSON upload and queue APKG export.

    Args:
        request: Multipart request with deck field and one JSON upload.

    Returns:
        A redirect to the live job page, or the form with validation errors.
    """
    data = await request.form(max_files=1, max_fields=10)
    values = _text_values(data)
    cards = _cards_file(data)
    try:
        form = ExportForm.model_validate(values)
    except ValidationError as error:
        return _render(
            request,
            values=values,
            errors=form_errors(error.errors(), locale_from_request(request)),
            status=400,
        )
    try:
        generator = load_generator_config(request.app.state.settings.generator_path)
    except FlashcardError as error:
        return _render(
            request,
            values=values,
            errors={
                "form": translate_request(
                    request,
                    "Generator configuration cannot be used: {error}",
                    de="Generator-Konfiguration nicht nutzbar: {error}",
                    error=error,
                )
            },
            status=400,
        )
    deck = form.deck or generator.config.generation.deck
    errors = _submission_errors(
        request, cards, deck, form.target, request.app.state.sync_service.configured
    )
    if errors:
        return _render(request, values=values, errors=errors, status=400)
    try:
        job = await run_in_threadpool(
            _create_job,
            request.app.state.jobs,
            request.app.state.worker,
            cards,
            deck,
            form.target,
            locale_from_request(request),
        )
    except (UploadError, OSError) as error:
        return _render(request, values=values, errors={"cards": str(error)}, status=400)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@router.get("/export/jobs/{job_id}/file")
def export_download(request: Request, job_id: str) -> FileResponse:
    """Download the APKG created by a completed export job.

    Args:
        request: Incoming request.
        job_id: Identifier of the export job.

    Returns:
        The new APKG as an attachment named after its target deck.

    Raises:
        HTTPException: If the job or output file is unavailable.
    """
    job = _completed_job(request, job_id)
    if job.options.get("target", "new_apkg") == ExportTarget.COLLECTION.value:
        raise HTTPException(status_code=404, detail="Für die Sammlung gibt es keine APKG-Datei")
    path = request.app.state.jobs.job_dir(job.id) / EXPORT_FILE
    if not path.exists():
        raise HTTPException(status_code=404, detail="Export-Datei nicht vorhanden")
    deck = str(job.options.get("deck", "karten"))
    name = clean_filename(deck.replace("::", " - "))
    return FileResponse(path, filename=f"{name}.apkg")


def _text_values(data: FormData) -> dict[str, str]:
    """Read the text values of an export form.

    Args:
        data: Parsed multipart form data.

    Returns:
        Text field name to final submitted value.
    """
    return {name: str(data.getlist(name)[-1]) for name in data.keys() if name != "cards"}


def _cards_file(data: FormData) -> UploadFile | None:
    """Return the non-empty card JSON upload of an export form.

    Args:
        data: Parsed multipart form data.

    Returns:
        The uploaded JSON file, or None for an empty or malformed field.
    """
    value = data.get("cards")
    return value if isinstance(value, UploadFile) and value.filename else None


def _submission_errors(
    request: Request,
    cards: UploadFile | None,
    deck: str,
    target: ExportTarget,
    sync_configured: bool,
) -> dict[str, str]:
    """Check that export has a card JSON and a target deck.

    Args:
        request: Browser request selecting validation-message language.
        cards: Uploaded card JSON, or None.
        deck: Effective target deck from the form or generator YAML.
        target: Selected APKG or synchronized collection destination.
        sync_configured: Whether a collection write can authenticate safely.

    Returns:
        Field errors; empty when the job may be created.
    """
    errors = {}
    if not deck:
        errors["deck"] = translate_request(
            request,
            "Specify a target deck or set one in the configuration.",
            de="Bitte ein Ziel-Deck angeben oder in der Konfiguration setzen.",
        )
    if target is ExportTarget.COLLECTION and not sync_configured:
        errors["target"] = translate_request(
            request,
            "Set up synchronisation before using the collection.",
            de="Für die Sammlung zuerst die Synchronisierung einrichten.",
        )
    if cards is None:
        return errors | {
            "cards": translate_request(
                request, "Select a card JSON file.", de="Bitte eine Karten-JSON-Datei auswählen."
            )
        }
    try:
        check_upload(clean_filename(cards.filename), cards.size, CARD_JSON)
    except UploadError as error:
        errors["cards"] = str(error)
    return errors


def _create_job(
    store: JobStore,
    worker: JobWorker,
    cards: UploadFile | None,
    deck: str,
    target: ExportTarget,
    locale: str,
) -> Job:
    """Store card JSON as a job and submit the APKG export.

    Args:
        store: Job storage receiving the JSON file.
        worker: Serial worker that runs the export.
        cards: Checked card JSON upload.
        deck: Non-empty normalized target deck.
        target: APKG or synchronized collection destination.
        locale: Interface language captured for background job notices.

    Returns:
        Newly queued export job.

    Raises:
        UploadError: If the upload changes before storage.
        OSError: If the job folder cannot be created or written.
    """
    if cards is None:
        raise UploadError("Bitte eine Karten-JSON-Datei auswählen.")
    job = store.create(
        cards.file,
        cards.filename,
        cards.size,
        {"kind": EXPORT_KIND, "deck": deck, "target": target.value, "locale": locale},
        upload_kind=CARD_JSON,
    )
    worker.submit(job)
    return job


def _completed_job(request: Request, job_id: str) -> Job:
    """Load a successful APKG-export job.

    Args:
        request: Incoming request with the job store.
        job_id: Identifier from the path.

    Returns:
        Completed export job.

    Raises:
        HTTPException: If the job is unknown, unfinished, failed, or another kind.
    """
    job = request.app.state.jobs.get(job_id)
    if job is None or job.status is not JobStatus.DONE or job.options.get("kind") != EXPORT_KIND:
        raise HTTPException(status_code=404, detail="Export-Datei nicht vorhanden")
    return job


def _render(
    request: Request,
    *,
    values: dict[str, str],
    errors: dict[str, str],
    status: int = 200,
) -> HTMLResponse:
    """Render the export form with default deck and validation errors.

    Args:
        request: Incoming request.
        values: Previously submitted text values.
        errors: Field name to German error message.
        status: HTTP status of the response.

    Returns:
        The rendered form.
    """
    context: dict[str, Any] = {
        "values": values,
        "errors": errors,
        "default_deck": "",
        "max_size": CARD_JSON.limit_text,
        "config_error": None,
    }
    try:
        context["default_deck"] = load_generator_config(
            request.app.state.settings.generator_path
        ).config.generation.deck
    except FlashcardError as error:
        context["config_error"] = str(error)
    return request.app.state.templates.TemplateResponse(
        request, "export.html", context, status_code=status
    )
