"""List jobs, show one job, and cancel it (AS-004, AS-032)."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from anki_studio.jobs import Job

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
    context = {
        "job": job,
        "form": job.options.get("form", {}),
        "target_file": job.options.get("target_file"),
        "events": request.app.state.jobs.read_events(job.id),
    }
    return request.app.state.templates.TemplateResponse(request, "job.html", context)


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
