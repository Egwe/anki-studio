"""Show the state of the structured PDF mode and start the model download (AS-010)."""

from anki_flashcards.errors import FlashcardError
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from anki_studio.generator_config import load_generator_config
from anki_studio.models_task import MODELS_KIND, MODELS_TITLE, structured_state

router = APIRouter()


@router.get("/settings/models", response_class=HTMLResponse)
async def models_page(request: Request) -> HTMLResponse:
    """Show Docling, GPU, and model components of the structured mode.

    Args:
        request: Incoming request.

    Returns:
        The page; a broken generator YAML is explained instead.
    """
    context: dict[str, object] = {"state": None, "error": None}
    try:
        config = load_generator_config(request.app.state.settings.generator_path).config
        context["state"] = await run_in_threadpool(structured_state, config)
        context["formula_batch_size"] = config.pdf_conversion.formula_batch_size
    except FlashcardError as error:
        context["error"] = str(error)
    return request.app.state.templates.TemplateResponse(request, "structured.html", context)


@router.post("/settings/models/download")
def download_models(request: Request) -> RedirectResponse:
    """Queue a job that downloads the missing models.

    Args:
        request: Incoming request.

    Returns:
        A redirect to the job page with live progress.
    """
    store = request.app.state.jobs
    job = store.create_task(MODELS_TITLE, {"kind": MODELS_KIND})
    request.app.state.worker.submit(job)
    return RedirectResponse(f"/jobs/{job.id}", status_code=303)
