"""Review cards of a job, write them, and download the results (AS-005, AS-006).

Card changes answer with HTML fragments for htmx (status 200, also for
validation errors, because htmx does not swap error responses).
"""

from typing import Annotated, Any

from anki_flashcards.errors import FlashcardError
from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from anki_studio.collection_write import COLLECTION_WRITE_KIND, COLLECTION_WRITE_TITLE
from anki_studio.generation import SOURCE_TEXT_FILE, job_paths
from anki_studio.jobs import Job
from anki_studio.review import (
    AlreadyWrittenError,
    ReviewError,
    UnknownCardError,
    clear_finished_collection_write,
    delete_card,
    export_json,
    load_result,
    load_review,
    reserve_collection_write,
    set_selected,
    update_card,
    write_reviewed,
)
from anki_studio.routes.jobs import job_context
from anki_studio.uploads import clean_filename

router = APIRouter()


class CardForm(BaseModel):
    """Hold the entered fields of one card; the generator validates them.

    Attributes:
        front: Question.
        back: Answer.
        tags: Tags separated by spaces.
        subdeck: Single-level subdeck, empty for none.
    """

    front: str = ""
    back: str = ""
    tags: str = ""
    subdeck: str = ""


class WriteForm(BaseModel):
    """Hold the deck chosen for writing.

    Attributes:
        deck: Target deck; ``::`` separates levels.
    """

    deck: str = ""


@router.get("/jobs/{job_id}/cards/{card_id}", response_class=HTMLResponse)
def show_card(request: Request, job_id: str, card_id: str) -> HTMLResponse:
    """Render one card in view mode, for example after cancelling an edit.

    Args:
        request: Incoming request.
        job_id: Identifier of the job.
        card_id: Identifier of the card.

    Returns:
        The card fragment.

    Raises:
        HTTPException: 404 for unknown jobs or cards.
    """
    job = _done_job(request, job_id)
    return _fragment(request, job, mode="view", entry=_entry(request, job, card_id))


@router.get("/jobs/{job_id}/cards/{card_id}/edit", response_class=HTMLResponse)
def edit_card(request: Request, job_id: str, card_id: str) -> HTMLResponse:
    """Render one card as an edit form.

    Args:
        request: Incoming request.
        job_id: Identifier of the job.
        card_id: Identifier of the card.

    Returns:
        The edit fragment filled with the stored values.

    Raises:
        HTTPException: 404 for unknown jobs or cards.
    """
    job = _done_job(request, job_id)
    entry = _entry(request, job, card_id)
    values = {
        "front": entry.card.front,
        "back": entry.card.back,
        "tags": " ".join(entry.card.tags),
        "subdeck": entry.card.subdeck or "",
    }
    return _fragment(request, job, mode="edit", entry=entry, values=values)


@router.post("/jobs/{job_id}/cards/{card_id}", response_class=HTMLResponse)
async def save_card(
    request: Request, job_id: str, card_id: str, form: Annotated[CardForm, Form()]
) -> HTMLResponse:
    """Validate and store an edited card.

    Args:
        request: Incoming request.
        job_id: Identifier of the job.
        card_id: Identifier of the card.
        form: Entered fields.

    Returns:
        The card in view mode, or the edit form with the entered values and
        the reason why they were refused.

    Raises:
        HTTPException: 404 for unknown jobs.
    """
    job = _done_job(request, job_id)
    values = form.model_dump()
    try:
        entry = await run_in_threadpool(update_card, request.app.state.jobs, job, card_id, values)
    except ReviewError as error:
        entry = _entry(request, job, card_id)
        return _fragment(request, job, mode="edit", entry=entry, values=values, error=str(error))
    return _fragment(request, job, mode="view", entry=entry, count=True)


@router.post("/jobs/{job_id}/cards/{card_id}/select", response_class=HTMLResponse)
async def select_card(request: Request, job_id: str, card_id: str) -> HTMLResponse:
    """Select or deselect a card; the checkbox sends ``selected=true`` when checked.

    Args:
        request: Incoming request.
        job_id: Identifier of the job.
        card_id: Identifier of the card.

    Returns:
        The card in view mode and the updated counter.

    Raises:
        HTTPException: 404 for unknown jobs or cards, 409 after writing.
    """
    job = _done_job(request, job_id)
    selected = (await request.form()).get("selected") == "true"
    entry = await _apply(set_selected, request, job, card_id, selected)
    return _fragment(request, job, mode="view", entry=entry, count=True)


@router.post("/jobs/{job_id}/cards/{card_id}/delete", response_class=HTMLResponse)
async def remove_card(request: Request, job_id: str, card_id: str) -> HTMLResponse:
    """Delete a card from the review.

    Args:
        request: Incoming request.
        job_id: Identifier of the job.
        card_id: Identifier of the card.

    Returns:
        Only the updated counter; the card element is replaced by nothing.

    Raises:
        HTTPException: 404 for unknown jobs or cards, 409 after writing.
    """
    job = _done_job(request, job_id)
    await _apply(delete_card, request, job, card_id)
    return _fragment(request, job, mode="none", count=True)


@router.post("/jobs/{job_id}/write", response_class=HTMLResponse)
async def write_job(request: Request, job_id: str, form: Annotated[WriteForm, Form()]) -> Response:
    """Write reviewed cards into their APKG or queued collection target.

    Args:
        request: Incoming request.
        job_id: Identifier of the job.
        form: Chosen deck.

    Returns:
        A redirect to the completed APKG result or the live collection-write
        job, or the source job page with an error (status 400).

    Raises:
        HTTPException: 404 for unknown jobs.
    """
    job = _done_job(request, job_id)
    if job.options.get("form", {}).get("target") == "collection":
        return await _queue_collection_write(request, job, form.deck)
    try:
        await run_in_threadpool(write_reviewed, request.app.state.jobs, job, form.deck)
    except (ReviewError, FlashcardError) as error:
        context = job_context(request, job) | {"write_error": str(error), "deck_value": form.deck}
        return request.app.state.templates.TemplateResponse(
            request, "job.html", context, status_code=400
        )
    return RedirectResponse(f"/jobs/{job.id}#result", status_code=303)


async def _queue_collection_write(request: Request, job: Job, deck: str) -> Response:
    """Reserve a review and queue its pre-sync/write/post-sync task.

    Args:
        request: Incoming request with the jobs and background worker.
        job: Finished generation job with collection target.
        deck: Target deck text entered in the review form.

    Returns:
        Redirect to the dedicated live write job, or source job page with a
        validation error.
    """
    store = request.app.state.jobs
    write_job = store.create_task(
        COLLECTION_WRITE_TITLE,
        {"kind": COLLECTION_WRITE_KIND, "source_job_id": job.id},
    )
    try:
        await run_in_threadpool(reserve_collection_write, store, job, write_job.id, deck)
    except ReviewError as error:
        store.delete(write_job.id)
        context = job_context(request, job) | {"write_error": str(error), "deck_value": deck}
        return request.app.state.templates.TemplateResponse(
            request, "job.html", context, status_code=400
        )
    request.app.state.worker.submit(write_job)
    return RedirectResponse(f"/jobs/{write_job.id}", status_code=303)


@router.get("/jobs/{job_id}/files/{kind}")
async def download(request: Request, job_id: str, kind: str) -> FileResponse:
    """Download the written APKG, the selected cards as JSON, or the source text.

    Args:
        request: Incoming request.
        job_id: Identifier of the job.
        kind: ``apkg``, ``json``, or ``source``.

    Returns:
        The file as attachment with a name derived from the deck.

    Raises:
        HTTPException: 404 if the file does not exist (yet), 409 if no card
            is selected for the JSON download.
    """
    job = _done_job(request, job_id)
    store = request.app.state.jobs
    result = load_result(store, job)
    deck = (result or {}).get("deck") or load_review(store, job).deck or job.source_name
    name = clean_filename(deck.replace("::", " - "))
    if kind == "apkg" and result is not None and result.get("target") != "collection":
        return FileResponse(job_paths(store, job).output, filename=f"{name}.apkg")
    if kind == "json":
        try:
            path = await run_in_threadpool(export_json, store, job)
        except ReviewError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return FileResponse(path, filename=f"{name}.cards.json", media_type="application/json")
    source = store.job_dir(job.id) / SOURCE_TEXT_FILE
    if kind == "source" and source.exists():
        return FileResponse(source, filename=f"{name}.md", media_type="text/markdown")
    raise HTTPException(status_code=404, detail="Datei nicht vorhanden")


async def _apply(change: Any, request: Request, job: Job, *args: Any) -> Any:
    """Run a review change in the thread pool and map refusals to HTTP errors.

    Args:
        change: Review function taking store, job, and ``args``.
        request: Incoming request.
        job: Job under review.
        *args: Further arguments of the change.

    Returns:
        The value returned by the change.

    Raises:
        HTTPException: 404 for unknown cards, 409 after writing.
    """
    try:
        return await run_in_threadpool(change, request.app.state.jobs, job, *args)
    except AlreadyWrittenError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except UnknownCardError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


def _done_job(request: Request, job_id: str) -> Job:
    """Load a finished job with generated cards or answer 404.

    Args:
        request: Incoming request.
        job_id: Identifier from the URL.

    Returns:
        The job.

    Raises:
        HTTPException: 404 if the job is unknown or has no cards.
    """
    job = request.app.state.jobs.get(job_id)
    if job is None or job.status.value != "done":
        raise HTTPException(status_code=404, detail="Keine Karten zu diesem Job")
    clear_finished_collection_write(request.app.state.jobs, job)
    return job


def _entry(request: Request, job: Job, card_id: str) -> Any:
    """Find one card of the review or answer 404.

    Args:
        request: Incoming request.
        job: Job under review.
        card_id: Identifier of the card.

    Returns:
        The ``ReviewCard``.

    Raises:
        HTTPException: 404 if the card does not exist.
    """
    review = load_review(request.app.state.jobs, job)
    entry = next((card for card in review.cards if card.id == card_id), None)
    if entry is None:
        raise HTTPException(status_code=404, detail="Karte nicht gefunden")
    return entry


def _fragment(request: Request, job: Job, **context: Any) -> HTMLResponse:
    """Render a card fragment, optionally with the out-of-band counter.

    Args:
        request: Incoming request.
        job: Job under review.
        **context: ``mode`` (``view``, ``edit``, ``none``), ``entry``,
            ``values``, ``error`` and ``count``.

    Returns:
        The rendered fragment.
    """
    if context.get("count"):
        context["review"] = load_review(request.app.state.jobs, job)
    return request.app.state.templates.TemplateResponse(
        request, "_review_fragment.html", {"job": job, **context}
    )
