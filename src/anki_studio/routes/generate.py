"""Show the generation form and turn a submission into jobs (AS-001 to AS-003)."""

import json
from collections.abc import Sequence
from typing import Any

from anki_flashcards.apkg import collection_decks
from anki_flashcards.errors import FlashcardError
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, UploadFile

from anki_studio.collection_worker import CollectionWorkerError, CollectionWorkerStoppedError
from anki_studio.forms import GenerateForm, Target, form_errors
from anki_studio.generation import TARGET_DIR, job_options, transfer_notice
from anki_studio.generator_config import (
    GeneratorConfig,
    effective_settings,
    load_generator_config,
    profile_views,
)
from anki_studio.i18n import locale_from_request, translate_request
from anki_studio.jobs import JobStore
from anki_studio.limits import MAX_DOCUMENTS
from anki_studio.uploads import APKG, DOCUMENT, UploadError, check_upload, clean_filename
from anki_studio.worker import JobWorker

FILE_FIELDS = frozenset({"documents", "target_apkg"})

router = APIRouter()


@router.get("/generate", response_class=HTMLResponse)
def generate_page(request: Request) -> HTMLResponse:
    """Show the generation form with the defaults of the generator YAML.

    Args:
        request: Incoming request.

    Returns:
        The rendered form.
    """
    return _render(request, values={}, errors={})


@router.post("/generate", response_class=HTMLResponse)
async def generate_submit(request: Request) -> Response:
    """Validate a submission, create one job per document, and queue them.

    Args:
        request: Multipart request of the generation form.

    Returns:
        A redirect to the job (one document) or the job list, or the form
        with status 400 and messages per field.
    """
    data = await request.form(max_files=MAX_DOCUMENTS + 1, max_fields=60)
    values = _text_values(data)
    documents = _files(data.getlist("documents"))
    package = next(iter(_files(data.getlist("target_apkg"))), None)
    try:
        form = GenerateForm.model_validate(values)
    except ValidationError as error:
        return _render(
            request,
            values=values,
            errors=form_errors(error.errors(), locale_from_request(request)),
            status=400,
        )
    errors = _submission_errors(request, form, documents, package)
    if errors:
        return _render(request, values=values, errors=errors, status=400)
    job_ids = await run_in_threadpool(
        _create_jobs,
        request.app.state.jobs,
        request.app.state.worker,
        form,
        documents,
        package,
        locale_from_request(request),
    )
    location = f"/jobs/{job_ids[0]}" if len(job_ids) == 1 else "/jobs"
    return RedirectResponse(location, status_code=303)


def _text_values(data: FormData) -> dict[str, str]:
    """Collect the text fields of a form; the last value of a name wins.

    The last value matters for yes/no options, which send a hidden
    ``false`` followed by the checkbox's ``true``.

    Args:
        data: Parsed multipart form.

    Returns:
        Field name to text value, without file fields.
    """
    return {name: str(data.getlist(name)[-1]) for name in data.keys() if name not in FILE_FIELDS}


def _files(entries: Sequence[Any]) -> list[UploadFile]:
    """Keep the real file uploads of a form field.

    Args:
        entries: Values of a file field; empty file inputs send no name.

    Returns:
        The uploaded files with a file name.
    """
    return [entry for entry in entries if isinstance(entry, UploadFile) and entry.filename]


def _submission_errors(
    request: Request, form: GenerateForm, documents: list[UploadFile], package: UploadFile | None
) -> dict[str, str]:
    """Check files, target, and the effective settings of a submission.

    Args:
        request: Incoming request; gives access to the settings.
        form: Validated form fields.
        documents: Uploaded documents.
        package: Uploaded APKG to extend, or None.

    Returns:
        Field name to German message; empty if the jobs may be created.
    """
    errors = _document_errors(request, documents) | _target_errors(
        request, form, documents, package
    )
    try:
        generator = load_generator_config(request.app.state.settings.generator_path)
    except FlashcardError as error:
        return errors | {
            "form": translate_request(
                request,
                "Generator configuration cannot be used: {error}",
                de="Generator-Konfiguration nicht nutzbar: {error}",
                error=error,
            )
        }
    return errors | _settings_errors(request, generator, form)


def _document_errors(request: Request, documents: list[UploadFile]) -> dict[str, str]:
    """Check number, types, and sizes of the uploaded documents.

    Args:
        request: Browser request selecting validation-message language.
        documents: Uploaded documents.

    Returns:
        A message for ``documents`` if something is wrong, otherwise empty.
    """
    if not documents:
        return {
            "documents": translate_request(
                request,
                "Select at least one document.",
                de="Bitte mindestens ein Dokument auswählen.",
            )
        }
    if len(documents) > MAX_DOCUMENTS:
        return {
            "documents": translate_request(
                request,
                "At most {count} documents at once.",
                de="Höchstens {count} Dokumente auf einmal.",
                count=MAX_DOCUMENTS,
            )
        }
    try:
        for document in documents:
            check_upload(clean_filename(document.filename), document.size, DOCUMENT)
    except UploadError as error:
        return {"documents": str(error)}
    return {}


def _target_errors(
    request: Request, form: GenerateForm, documents: list[UploadFile], package: UploadFile | None
) -> dict[str, str]:
    """Check the APKG upload when a package is to be extended.

    Args:
        request: Incoming request, used to check whether the collection
            target can synchronize.
        form: Validated form fields.
        documents: Uploaded documents.
        package: Uploaded APKG, or None.

    Returns:
        A message for ``target_apkg`` if something is wrong, otherwise empty.
    """
    if form.target is Target.COLLECTION:
        if request.app.state.sync_service.configured:
            return {}
        return {
            "target": translate_request(
                request,
                "Set up synchronisation before using the collection.",
                de="Für die Sammlung zuerst die Synchronisierung einrichten.",
            )
        }
    if form.target is not Target.EXTEND_APKG:
        return {}
    if package is None:
        return {
            "target_apkg": translate_request(
                request,
                "Select the APKG file to extend.",
                de="Bitte die APKG-Datei wählen, die erweitert werden soll.",
            )
        }
    if len(documents) > 1:
        return {
            "target_apkg": translate_request(
                request,
                "An APKG can only be extended with one document at a time.",
                de="Eine APKG lässt sich nur mit einem Dokument zugleich erweitern.",
            )
        }
    try:
        check_upload(clean_filename(package.filename), package.size, APKG)
    except UploadError as error:
        return {"target_apkg": str(error)}
    return {}


def _settings_errors(
    request: Request, generator: GeneratorConfig, form: GenerateForm
) -> dict[str, str]:
    """Resolve the effective settings and require a transfer confirmation.

    Args:
        request: Browser request selecting validation-message language.
        generator: Loaded generator configuration.
        form: Validated form fields.

    Returns:
        A message for ``form`` or ``confirm_transfer``, otherwise empty.
    """
    try:
        settings = effective_settings(generator, form.generator_values())
    except FlashcardError as error:
        return {"form": str(error)}
    notice = transfer_notice(settings)
    if notice is not None and not form.confirm_transfer:
        return {
            "confirm_transfer": f"{notice} "
            + translate_request(
                request, "Please confirm the transfer.", de="Bitte die Übertragung bestätigen."
            )
        }
    return {}


def _create_jobs(
    store: JobStore,
    worker: JobWorker,
    form: GenerateForm,
    documents: list[UploadFile],
    package: UploadFile | None,
    locale: str,
) -> list[str]:
    """Store the uploads as jobs and queue them; runs in a worker thread.

    Args:
        store: Job store.
        worker: Job worker that receives the jobs.
        form: Validated form fields.
        documents: Checked documents, one job each.
        package: Checked APKG to extend, or None.
        locale: Interface language captured for background job notices.

    Returns:
        The identifiers of the queued jobs in upload order.
    """
    target_file = clean_filename(package.filename) if package else None
    job_ids = []
    for document in documents:
        job = store.create(
            document.file,
            document.filename,
            document.size,
            job_options(form, target_file) | {"locale": locale},
        )
        if package is not None:
            store.add_file(job.id, TARGET_DIR, package.file, package.filename, package.size, APKG)
        worker.submit(job)
        job_ids.append(job.id)
    return job_ids


def _render(
    request: Request, *, values: dict[str, str], errors: dict[str, str], status: int = 200
) -> HTMLResponse:
    """Render the form with defaults, profiles, earlier input, and messages.

    Args:
        request: Incoming request.
        values: Raw values of a previous submission, empty for a new form.
        errors: Field name to message.
        status: HTTP status of the page.

    Returns:
        The rendered form; if the generator YAML cannot be loaded, the page
        explains why and offers no form.
    """
    context: dict[str, Any] = {"values": values, "errors": errors, "max_documents": MAX_DOCUMENTS}
    context["collection_decks"] = _collection_deck_names(request)
    try:
        context |= _config_context(
            request, load_generator_config(request.app.state.settings.generator_path)
        )
    except FlashcardError as error:
        context["config_error"] = str(error)
    return request.app.state.templates.TemplateResponse(
        request, "generate.html", context, status_code=status
    )


def _collection_deck_names(request: Request) -> tuple[str, ...]:
    """Return cached collection deck names for a browser datalist.

    A target form is still usable before the first sync: its future job will
    synchronize first and accepts a new deck name. The route only offers
    suggestions after a known successful synchronization and never opens the
    non-thread-safe collection outside its dedicated worker.

    Args:
        request: Incoming request with sync state and collection worker.

    Returns:
        Case-insensitively sorted normal deck names, or an empty tuple when
        no synchronized collection can currently be read.
    """
    try:
        if request.app.state.sync_service.state().last_synced_at is None:
            return ()
        entries = request.app.state.collection_worker.run(collection_decks)
    except (CollectionWorkerError, CollectionWorkerStoppedError, FlashcardError):
        return ()
    return tuple(sorted((str(entry["name"]) for entry in entries), key=str.casefold))


def _config_context(request: Request, generator: GeneratorConfig) -> dict[str, Any]:
    """Collect what the form shows from the generator configuration.

    Args:
        request: Browser request selecting the placeholder language.
        generator: Loaded generator configuration.

    Returns:
        Effective defaults, profile descriptions, the picture-capable
        profiles, and the PDF mode per profile as JSON for the browser.
    """
    defaults = effective_settings(generator, {})
    profiles = profile_views(generator)
    modes = {"": defaults.pdf_mode.value} | {view.name: view.pdf_mode.value for view in profiles}
    return {
        "defaults": defaults,
        "profiles": profiles,
        "picture_profiles": [view for view in profiles if view.image_input],
        "profile_modes": json.dumps(modes),
        "config_path": str(generator.path),
        "deck_placeholder": generator.config.generation.deck
        or translate_request(request, "Filename without extension", de="Dateiname ohne Endung"),
    }
