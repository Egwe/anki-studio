"""Tests for the live job page with Server-Sent Events (AS-004)."""

import io
import threading
from typing import Any

import pytest
from anki_flashcards import pipeline
from anki_flashcards.models import Card
from fastapi.testclient import TestClient

from anki_studio.jobs import JobStatus, JobStore
from anki_studio.sse import sse_message
from tests.conftest import wait_until


def test_sse_message_format() -> None:
    """Multi-line data becomes several data fields; the id is optional."""
    assert sse_message("line", "<li>a</li>\n<li>b</li>", 3) == (
        "event: line\nid: 3\ndata: <li>a</li>\ndata: <li>b</li>\n\n"
    )
    assert sse_message("done", "") == "event: done\ndata: \n\n"


def finished_job(store: JobStore) -> str:
    """Create a job with a typical event log and mark it done.

    Args:
        store: Job store of the running application.

    Returns:
        The job identifier.
    """
    job = store.create(io.BytesIO(b"# T"), "skript.md", 3, {"form": {}, "target_file": None})
    for event in (
        {"type": "job_status", "status": "running", "message": None},
        {
            "type": "stage_started",
            "stage": "generation",
            "description": "Generating cards with AI...",
        },
        {
            "type": "stage_progress",
            "stage": "generation",
            "label": "Chunk",
            "completed": 1,
            "total": 2,
            "cards": 3,
        },
        {
            "type": "stage_progress",
            "stage": "generation",
            "label": "Chunk",
            "completed": 2,
            "total": 2,
            "cards": 5,
        },
        {"type": "cards_saved", "count": 5, "deck": "EL1"},
        {"type": "job_status", "status": "done", "message": None},
    ):
        store.append_event(job.id, event)
    store.update(job.id, JobStatus.DONE)
    return job.id


def read_stream(client: TestClient, url: str, headers: dict[str, str] | None = None) -> str:
    """Read a complete event stream.

    Args:
        client: Logged-in test client.
        url: Stream URL.
        headers: Extra request headers.

    Returns:
        The whole response body.
    """
    with client.stream("GET", url, headers=headers or {}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        return "".join(response.iter_text())


def test_stream_of_finished_job_sends_history_and_done(auth_client: TestClient) -> None:
    """A finished job's stream replays its events and ends with ``done``.

    Args:
        auth_client: Logged-in test client.
    """
    job_id = finished_job(auth_client.app.state.jobs)

    body = read_stream(auth_client, f"/jobs/{job_id}/events")

    assert body.count("event: line") == 5
    assert 'id: 4\ndata: <li class="event progress-line">Chunk: 2 von 2 · 5 Karten</li>' in body
    assert "Chunk: 1 von 2" not in body.split("event: progress")[0]
    assert body.count("event: progress") == 2
    assert body.count("event: status") == 2
    assert "5 Karten erzeugt" in body
    assert body.rstrip().endswith(
        'hx-select="#job-main" hx-target="#job-main" hx-swap="outerHTML"></div>'
    )
    assert "event: done" in body


def test_stream_resumes_after_known_events(auth_client: TestClient) -> None:
    """``start`` and ``Last-Event-ID`` skip events the page already has.

    Args:
        auth_client: Logged-in test client.
    """
    job_id = finished_job(auth_client.app.state.jobs)

    from_start = read_stream(auth_client, f"/jobs/{job_id}/events?start=5")
    resumed = read_stream(auth_client, f"/jobs/{job_id}/events?start=0", {"Last-Event-ID": "5"})

    for body in (from_start, resumed):
        assert body.count("event: line") == 1
        assert "id: 6" in body
        assert "5 Karten erzeugt" not in body


def test_running_job_streams_live_until_done(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Progress of a running job arrives while it runs; the stream then ends.

    Args:
        auth_client: Logged-in test client.
        monkeypatch: Pytest fixture for replacing the AI call.
    """
    release = threading.Event()

    def slow_generate_cards(document: Any, ai: Any, **kwargs: Any) -> list[Card]:
        """Report one chunk, then wait until the test releases the job.

        Args:
            document: Extracted document.
            ai: Provider settings.
            **kwargs: Generation options including ``progress``.

        Returns:
            One card.
        """
        kwargs["progress"](1, 2, 1)
        release.wait(5)
        kwargs["progress"](2, 2, 1)
        return [Card(front="Was ist Ohm?", back="Einheit")]

    monkeypatch.setattr(pipeline, "generate_cards", slow_generate_cards)
    response = auth_client.post(
        "/generate",
        files=[("documents", ("skript.md", io.BytesIO(b"# Ohm"), "text/markdown"))],
        follow_redirects=False,
    )
    job_id = response.headers["location"].rsplit("/", 1)[-1]
    store = auth_client.app.state.jobs
    wait_until(lambda: any(e["type"] == "stage_progress" for e in store.read_events(job_id)))

    page = auth_client.get(f"/jobs/{job_id}").text
    assert 'sse-connect="http://testserver/jobs/' in page
    assert '<progress value="1" max="2">' in page
    threading.Timer(0.3, release.set).start()
    body = read_stream(auth_client, f"/jobs/{job_id}/events?start=0")

    assert "Chunk: 2 von 2" in body
    assert "1 Karten erzeugt" in body
    assert 'class="status status-done"' in body
    assert body.rstrip().endswith("</div>")
    assert "sse-connect" not in auth_client.get(f"/jobs/{job_id}").text


def test_finished_page_has_no_live_connection(auth_client: TestClient) -> None:
    """A finished job page needs no event stream and shows no progress bar.

    Args:
        auth_client: Logged-in test client.
    """
    job_id = finished_job(auth_client.app.state.jobs)

    page = auth_client.get(f"/jobs/{job_id}").text

    assert "sse-connect" not in page
    assert "<progress" not in page
    assert 'http-equiv="refresh"' not in page
    assert "5 Karten erzeugt" in page


def test_stream_needs_login_and_existing_job(client: TestClient, auth_client: TestClient) -> None:
    """Anonymous streams are refused; unknown jobs answer 404.

    Args:
        client: Anonymous test client.
        auth_client: Logged-in test client.
    """
    anonymous = client.get("/jobs/" + "0" * 32 + "/events", follow_redirects=False)

    assert anonymous.status_code == 303
    assert auth_client.get("/jobs/" + "0" * 32 + "/events").status_code == 404
