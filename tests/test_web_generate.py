"""Tests for the generation form and the job pages (AS-001 to AS-004)."""

import io
import json
from pathlib import Path
from typing import Any

import pytest
from anki_flashcards import pipeline
from anki_flashcards.apkg import create_apkg
from anki_flashcards.models import Card
from fastapi.testclient import TestClient

from anki_studio.generation import CARDS_FILE, TARGET_DIR
from anki_studio.settings import StudioSettings
from tests.conftest import wait_until


@pytest.fixture(autouse=True)
def fake_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace the AI call of the pipeline with one fixed card.

    Args:
        monkeypatch: Pytest fixture for replacing attributes.
    """

    def generate_cards(document: Any, ai: Any, **kwargs: Any) -> list[Card]:
        """Return one card and report one chunk.

        Args:
            document: Extracted document.
            ai: Provider settings.
            **kwargs: Generation options including ``progress``.

        Returns:
            One card.
        """
        kwargs["progress"](1, 1, 1)
        return [Card(front="Was ist Ohm?", back="Einheit des Widerstands")]

    monkeypatch.setattr(pipeline, "generate_cards", generate_cards)


def markdown(name: str = "skript.md") -> tuple[str, io.BytesIO, str]:
    """Build a small Markdown upload.

    Args:
        name: File name sent by the browser.

    Returns:
        A ``files`` entry for the test client.
    """
    return (name, io.BytesIO(b"# Ohm\n\nWiderstand."), "text/markdown")


def submit(
    client: TestClient, data: dict[str, str], files: list[tuple[str, Any]] | None = None
) -> Any:
    """Post the generation form without following redirects.

    Args:
        client: Logged-in test client.
        data: Form fields.
        files: Multipart files; one Markdown document by default.

    Returns:
        The response.
    """
    files = [("documents", markdown())] if files is None else files
    return client.post("/generate", data=data, files=files, follow_redirects=False)


def job_dirs(settings: StudioSettings) -> list[Path]:
    """List the job folders that exist.

    Args:
        settings: Settings of the test application.

    Returns:
        Job folders below the data directory.
    """
    jobs = settings.data_dir / "jobs"
    return [path for path in jobs.iterdir() if path.is_dir()] if jobs.exists() else []


def test_form_shows_profiles_and_defaults(auth_client: TestClient) -> None:
    """The form lists the profiles and uses YAML values as placeholders.

    Args:
        auth_client: Logged-in test client.
    """
    page = auth_client.get("/generate").text

    assert "lokal – ollama/llama3.2" in page
    assert "nativ – openai/gpt-4o-mini (native, Schlüssel fehlt)" in page
    assert 'placeholder="Englisch"' in page
    assert "Dateiname ohne Endung" in page


def test_missing_generator_config_is_explained(
    auth_client: TestClient, studio_settings: StudioSettings
) -> None:
    """Without generator YAML the page explains the problem and has no form.

    Args:
        auth_client: Logged-in test client.
        studio_settings: Settings of the test application.
    """
    studio_settings.generator_config.unlink()

    page = auth_client.get("/generate").text

    assert "Generator-Konfiguration ist nicht nutzbar" in page
    assert "Karten erzeugen</button>" not in page


def test_submission_runs_job_and_saves_cards(
    auth_client: TestClient, studio_settings: StudioSettings
) -> None:
    """One document becomes one job whose page shows the result.

    Args:
        auth_client: Logged-in test client.
        studio_settings: Settings of the test application.
    """
    response = submit(auth_client, {"deck": "EL1", "limit": "5", "subdecks": "false"})

    assert response.status_code == 303
    job_id = response.headers["location"].rsplit("/", 1)[-1]
    wait_until(lambda: "fertig" in auth_client.get(f"/jobs/{job_id}").text)
    page = auth_client.get(f"/jobs/{job_id}").text
    assert "1 Karten erzeugt" in page
    assert "für Deck EL1" in page
    cards = studio_settings.data_dir / "jobs" / job_id / CARDS_FILE
    assert json.loads(cards.read_text(encoding="utf-8"))["deck"] == "EL1"
    assert "skript.md" in auth_client.get("/jobs").text


def test_several_documents_become_several_jobs(
    auth_client: TestClient, studio_settings: StudioSettings
) -> None:
    """Each uploaded file gets its own job; the list page is shown.

    Args:
        auth_client: Logged-in test client.
        studio_settings: Settings of the test application.
    """
    files = [("documents", markdown("a.md")), ("documents", markdown("b.md"))]

    response = submit(auth_client, {}, files)

    assert response.headers["location"] == "/jobs"
    assert len(job_dirs(studio_settings)) == 2


@pytest.mark.parametrize(
    ("data", "files", "message"),
    [
        ({"limit": "-1"}, None, "mindestens 0"),
        ({"chunk_size": "999"}, None, "mindestens 1000"),
        ({}, [], "mindestens ein Dokument"),
        ({}, [("documents", ("bild.png", io.BytesIO(b"x"), "image/png"))], "nicht unterstützt"),
        ({"profile": "unbekannt"}, None, "Unknown model profile"),
        ({"profile": "nativ"}, None, "Bitte die Übertragung bestätigen"),
        ({"target": "extend_apkg"}, None, "APKG-Datei wählen"),
        ({"target": "collection"}, None, "Synchronisierung einrichten"),
    ],
)
def test_invalid_submissions_create_no_job(
    auth_client: TestClient,
    studio_settings: StudioSettings,
    data: dict[str, str],
    files: list[tuple[str, Any]] | None,
    message: str,
) -> None:
    """Invalid input returns the form with a message and no job folder.

    Args:
        auth_client: Logged-in test client.
        studio_settings: Settings of the test application.
        data: Form fields.
        files: Multipart files, or None for one Markdown document.
        message: Expected part of the message.
    """
    response = submit(auth_client, data, files)

    assert response.status_code == 400
    assert message in response.text
    assert job_dirs(studio_settings) == []


def test_confirmed_transfer_creates_job(
    auth_client: TestClient, studio_settings: StudioSettings
) -> None:
    """With confirmation a native job is accepted.

    Args:
        auth_client: Logged-in test client.
        studio_settings: Settings of the test application.
    """
    response = submit(auth_client, {"profile": "nativ", "confirm_transfer": "true"})

    assert response.status_code == 303
    assert len(job_dirs(studio_settings)) == 1


def test_extend_apkg_stores_package(
    auth_client: TestClient, studio_settings: StudioSettings, tmp_path: Path
) -> None:
    """The APKG to extend lands in the job's target folder.

    Args:
        auth_client: Logged-in test client.
        studio_settings: Settings of the test application.
        tmp_path: Temporary test folder.
    """
    package = tmp_path / "el1.apkg"
    create_apkg(package, "EL1", [Card(front="Alt", back="Karte")])
    files = [
        ("documents", markdown()),
        ("target_apkg", ("EL1.apkg", package.open("rb"), "application/octet-stream")),
    ]

    response = submit(auth_client, {"target": "extend_apkg", "deck": "EL1"}, files)

    job_id = response.headers["location"].rsplit("/", 1)[-1]
    assert (studio_settings.data_dir / "jobs" / job_id / TARGET_DIR / "EL1.apkg").exists()
    wait_until(lambda: "fertig" in auth_client.get(f"/jobs/{job_id}").text)


def test_extend_needs_single_document(auth_client: TestClient, tmp_path: Path) -> None:
    """An APKG can only be extended with one document at a time.

    Args:
        auth_client: Logged-in test client.
        tmp_path: Temporary test folder.
    """
    files = [
        ("documents", markdown("a.md")),
        ("documents", markdown("b.md")),
        ("target_apkg", ("EL1.apkg", io.BytesIO(b"PK"), "application/octet-stream")),
    ]

    response = submit(auth_client, {"target": "extend_apkg"}, files)

    assert response.status_code == 400
    assert "nur mit einem Dokument" in response.text


def test_invalid_form_keeps_values(auth_client: TestClient) -> None:
    """After an error the entered values are shown again.

    Args:
        auth_client: Logged-in test client.
    """
    page = submit(auth_client, {"deck": "Mein Deck", "limit": "-3"}).text

    assert 'value="Mein Deck"' in page
    assert 'aria-invalid="true"' in page


def test_cancel_waiting_job(auth_client: TestClient, studio_settings: StudioSettings) -> None:
    """A waiting job can be cancelled from its page.

    Args:
        auth_client: Logged-in test client.
        studio_settings: Settings of the test application.
    """
    store = auth_client.app.state.jobs
    job = store.create(
        io.BytesIO(b"# Titel"),
        "wartet.md",
        7,
        {"form": {}, "target_file": None, "locale": "de"},
    )

    response = auth_client.post(f"/jobs/{job.id}/cancel", follow_redirects=False)

    assert response.headers["location"] == f"/jobs/{job.id}"
    assert "Vom Benutzer abgebrochen." in auth_client.get(f"/jobs/{job.id}").text


@pytest.mark.parametrize("path", ["/jobs/" + "0" * 32, "/jobs/..%2F..%2Fetc"])
def test_unknown_job_is_404(auth_client: TestClient, path: str) -> None:
    """Unknown or invalid job identifiers answer with 404.

    Args:
        auth_client: Logged-in test client.
        path: Requested job page.
    """
    assert auth_client.get(path).status_code == 404


def test_generate_needs_login(client: TestClient, studio_settings: StudioSettings) -> None:
    """Anonymous uploads are redirected without creating a job.

    Args:
        client: Anonymous test client.
        studio_settings: Settings of the test application.
    """
    response = submit(client, {})

    assert response.headers["location"] == "/login"
    assert job_dirs(studio_settings) == []
