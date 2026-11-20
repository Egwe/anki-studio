"""List jobs, show one job live, and cancel it (AS-004, AS-032)."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from anki_studio.jobs import Job
from anki_studio.sse import KEEPALIVE, sse_message

POLL_SECONDS = 0.5
KEEPALIVE_SECONDS = 15.0
EXTRA_MESSAGES = {
    "stage_progress": ("progress", "progress_bar"),
    "job_status": ("status", "status_badge"),
}

router = APIRouter()


@router.get("/jobs", response_class=HTMLResponse)
def job_list(request: Request) -> HTMLResponse:
    """Show all jobs, newest first.

    Args:
        request: Incoming request.

    Returns:
        The rendered job list.
    """
    jobs = request.app.state.jobs.list_jobs()
    return request.app.state.templates.TemplateResponse(request, "jobs.html", {"jobs": jobs})


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_page(request: Request, job_id: str) -> HTMLResponse:
    """Show the state, options, and events of one job.

    Args:
        request: Incoming request.
        job_id: Identifier from the URL.

    Returns:
        The rendered job page.

    Raises:
        HTTPException: 404 if the job does not exist.
    """
    job = _job_or_404(request, job_id)
    events = request.app.state.jobs.read_events(job.id)
    progress = [event for event in events if event.get("type") == "stage_progress"]
    context = {
        "job": job,
        "form": job.options.get("form", {}),
        "target_file": job.options.get("target_file"),
        "events": events,
        "progress": progress[-1] if progress and not job.status.finished else None,
    }
    return request.app.state.templates.TemplateResponse(request, "job.html", context)


@router.get("/jobs/{job_id}/events")
def job_events(request: Request, job_id: str, start: int = 0) -> StreamingResponse:
    """Stream the job's new events as Server-Sent Events until it ends.

    Args:
        request: Incoming request; a ``Last-Event-ID`` header after a
            reconnect wins over ``start``.
        job_id: Identifier from the URL.
        start: Number of events the page already shows.

    Returns:
        A ``text/event-stream`` response with ``line``, ``progress``,
        ``status``, and finally ``done`` events.

    Raises:
        HTTPException: 404 if the job does not exist.
    """
    job = _job_or_404(request, job_id)
    resume = request.headers.get("last-event-id", "")
    position = int(resume) if resume.isdigit() else max(start, 0)
    return StreamingResponse(
        _stream(request, job.id, position),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@router.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str) -> RedirectResponse:
    """Cancel a waiting job or ask a running job to stop.

    Args:
        request: Incoming request.
        job_id: Identifier from the URL.

    Returns:
        A redirect back to the job page.

    Raises:
        HTTPException: 404 if the job does not exist.
    """
    job = _job_or_404(request, job_id)
    request.app.state.worker.cancel(job.id)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)


async def _stream(request: Request, job_id: str, position: int) -> AsyncIterator[str]:
    """Poll the event log and yield Server-Sent Events.

    The job file is read before the events: the worker appends the final
    status event before it marks the job as finished, so the last events
    are sent before ``done``.

    Args:
        request: Incoming request; the stream ends when the client leaves.
        job_id: Identifier of an existing job.
        position: Number of events the client already has.

    Yields:
        Formatted events, keepalive comments, and finally ``done``.
    """
    store = request.app.state.jobs
    fragments = request.app.state.templates.env.get_template("_events.html").module
    quiet = 0.0
    while not await request.is_disconnected():
        job = await run_in_threadpool(store.get, job_id)
        events = await run_in_threadpool(store.read_events, job_id, position)
        for event in events:
            position += 1
            for message in _messages(fragments, event, position):
                yield message
        if job is None or job.status.finished:
            url = str(request.url_for("job_page", job_id=job_id))
            yield sse_message("done", str(fragments.reload(url)).strip())
            return
        quiet = 0.0 if events else quiet + POLL_SECONDS
        if quiet >= KEEPALIVE_SECONDS:
            quiet = 0.0
            yield KEEPALIVE
        await asyncio.sleep(POLL_SECONDS)


def _messages(fragments: Any, event: dict[str, Any], position: int) -> list[str]:
    """Render the Server-Sent Events for one job event.

    Args:
        fragments: Template module of ``_events.html`` with its macros.
        event: Event from ``events.jsonl``.
        position: Number of events sent including this one; used as id.

    Returns:
        A ``line`` event if the event belongs in the history, plus a
        ``progress`` or ``status`` event for progress and status changes.
    """
    messages = []
    if fragments.shown(event):
        messages.append(sse_message("line", str(fragments.event_line(event)).strip(), position))
    extra = EXTRA_MESSAGES.get(event.get("type", ""))
    if extra is not None:
        name, macro = extra
        messages.append(sse_message(name, str(getattr(fragments, macro)(event)).strip()))
    return messages


def _job_or_404(request: Request, job_id: str) -> Job:
    """Load a job or answer with 404.

    Args:
        request: Incoming request.
        job_id: Identifier from the URL.

    Returns:
        The job.

    Raises:
        HTTPException: 404 for unknown or invalid identifiers.
    """
    job = request.app.state.jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    return job
