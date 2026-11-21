"""Upload an APKG and show its deck tree (AS-007, APKG part)."""

from anki_flashcards.apkg import collection_decks
from anki_flashcards.errors import FlashcardError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, UploadFile

from anki_studio.collection_worker import CollectionWorkerError, CollectionWorkerStoppedError
from anki_studio.decks import DECKS_FILE, DECKS_KIND, deck_tree, load_decks
from anki_studio.i18n import locale_from_request, translate_request
from anki_studio.jobs import Job, JobStatus, JobStore
from anki_studio.uploads import APKG, UploadError, check_upload, clean_filename
from anki_studio.worker import JobWorker

router = APIRouter()


@router.get("/decks", response_class=HTMLResponse)
def decks_page(request: Request) -> HTMLResponse:
    """Show synchronized collection decks and the APKG upload form.

    Args:
        request: Incoming request.

    Returns:
        The empty upload form.
    """
    return _render(request)


@router.post("/decks", response_class=HTMLResponse)
async def decks_submit(request: Request) -> Response:
    """Store an APKG and queue its inspection in the serial worker.

    Args:
        request: Multipart request with one APKG upload.

    Returns:
        A redirect to the live job page, or the form with an upload error.
    """
    data = await request.form(max_files=1, max_fields=5)
    package = _package(data)
    if package is None:
        return _render(
            request,
            error=translate_request(
                request, "Select an APKG file.", de="Bitte eine APKG-Datei auswählen."
            ),
            status=400,
        )
    try:
        check_upload(clean_filename(package.filename), package.size, APKG)
        job = await run_in_threadpool(
            _create_job,
            request.app.state.jobs,
            request.app.state.worker,
            package,
            locale_from_request(request),
        )
    except (UploadError, OSError) as error:
        return _render(request, error=str(error), status=400)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


@router.get("/decks/jobs/{job_id}", response_class=HTMLResponse)
def deck_result(request: Request, job_id: str) -> HTMLResponse:
    """Show the stored deck tree of a completed APKG-inspection job.

    Args:
        request: Incoming request.
        job_id: Identifier of the deck-inspection job.

    Returns:
        The nested deck tree with direct card counts.

    Raises:
        HTTPException: If this is not a completed deck-inspection job.
    """
    job = _completed_job(request, job_id)
    try:
        decks = load_decks(request.app.state.jobs.job_dir(job.id) / DECKS_FILE)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=404, detail="Deck result is not available") from error
    return request.app.state.templates.TemplateResponse(
        request, "deck_result.html", {"job": job, "decks": decks}
    )


def _package(data: FormData) -> UploadFile | None:
    """Return the non-empty APKG upload of a deck form.

    Args:
        data: Parsed multipart form data.

    Returns:
        The uploaded package, or None when the field is empty or malformed.
    """
    value = data.get("package")
    return value if isinstance(value, UploadFile) and value.filename else None


def _create_job(store: JobStore, worker: JobWorker, package: UploadFile, locale: str) -> Job:
    """Store one checked APKG as a job and submit it to the worker.

    Args:
        store: Job storage receiving the package.
        worker: Serial worker that inspects the APKG.
        package: Checked browser upload.
        locale: Interface language captured for background job notices.

    Returns:
        Newly queued deck-inspection job.

    Raises:
        UploadError: If the upload changes before it is stored.
        OSError: If the job folder cannot be created or written.
    """
    job = store.create(
        package.file,
        package.filename,
        package.size,
        {"kind": DECKS_KIND, "locale": locale},
        upload_kind=APKG,
    )
    worker.submit(job)
    return job


def _completed_job(request: Request, job_id: str) -> Job:
    """Load a successful job of the deck-inspection kind.

    Args:
        request: Incoming request with the job store.
        job_id: Identifier from the path.

    Returns:
        Completed deck-inspection job.

    Raises:
        HTTPException: If the job is unknown, unfinished, failed, or another kind.
    """
    job = request.app.state.jobs.get(job_id)
    if job is None or job.status is not JobStatus.DONE or job.options.get("kind") != DECKS_KIND:
        raise HTTPException(status_code=404, detail="Deck result is not available")
    return job


def _render(request: Request, *, error: str | None = None, status: int = 200) -> HTMLResponse:
    """Render the deck upload form.

    Args:
        request: Incoming request.
        error: Upload error to explain, if any.
        status: HTTP status of the response.

    Returns:
        The rendered form.
    """
    return request.app.state.templates.TemplateResponse(
        request,
        "decks.html",
        {"error": error, "max_size": APKG.limit_text, **_collection_context(request)},
        status_code=status,
    )


def _collection_context(request: Request) -> dict[str, object]:
    """Read the current local collection deck tree through its owner worker.

    The page never opens a collection itself. A tree is shown only after a
    successful sync, so its label does not imply that an untouched empty
    local file represents the server collection.

    Args:
        request: Incoming request with sync and collection services.

    Returns:
        Tree, last-sync timestamp, and a concise unavailable reason.
    """
    try:
        state = request.app.state.sync_service.state()
    except FlashcardError:
        return {
            "collection_decks": (),
            "collection_synced_at": None,
            "collection_error": translate_request(
                request, "Sync status cannot be read.", de="Sync-Status nicht lesbar."
            ),
        }
    if state.last_synced_at is None:
        return {
            "collection_decks": (),
            "collection_synced_at": None,
            "collection_error": translate_request(
                request, "Not synchronised yet.", de="Noch nicht synchronisiert."
            ),
        }
    try:
        decks = request.app.state.collection_worker.run(
            lambda collection: deck_tree(collection_decks(collection))
        )
    except (CollectionWorkerError, CollectionWorkerStoppedError, FlashcardError):
        return {
            "collection_decks": (),
            "collection_synced_at": state.last_synced_at,
            "collection_error": translate_request(
                request,
                "The local collection cannot be read right now.",
                de="Lokale Sammlung kann gerade nicht gelesen werden.",
            ),
        }
    return {
        "collection_decks": decks,
        "collection_synced_at": state.last_synced_at,
        "collection_error": None,
    }
