"""Tests for reviewing, writing, and downloading cards in the interface (AS-005, AS-006)."""

import io
import json
import zipfile

import pytest
from anki_flashcards.models import Card, save_cards
from fastapi.testclient import TestClient

from anki_studio.forms import GenerateForm
from anki_studio.generation import CARDS_FILE, SOURCE_TEXT_FILE, job_options
from anki_studio.jobs import JobStatus

CARDS = [
    Card(front="Was ist Ohm?", back="Einheit des Widerstands", tags=["Ohm"], subdeck="Grundlagen"),
    Card(front="Was ist Volt?", back="Einheit der Spannung"),
]


def done_job(client: TestClient, source_text: bool = False) -> str:
    """Create a finished job with two generated cards for deck EL1.

    Args:
        client: Logged-in test client.
        source_text: Whether a converted source text exists.

    Returns:
        The job identifier.
    """
    store = client.app.state.jobs
    options = job_options(GenerateForm.model_validate({"deck": "EL1"}))
    job = store.create(io.BytesIO(b"# T"), "skript.md", 3, options)
    folder = store.job_dir(job.id)
    save_cards(folder / CARDS_FILE, CARDS, deck="EL1", source="skript.md")
    if source_text:
        (folder / SOURCE_TEXT_FILE).write_text("[Seite 1]\nText", encoding="utf-8")
    store.update(job.id, JobStatus.DONE)
    return job.id


def test_finished_job_offers_review(auth_client: TestClient) -> None:
    """A finished job lists its cards, the counter, and the write form.

    Args:
        auth_client: Logged-in test client.
    """
    job_id = done_job(auth_client)

    page = auth_client.get(f"/jobs/{job_id}").text

    assert "Karten prüfen" in page
    assert "Was ist Ohm?" in page and "Grundlagen" in page
    assert "2 von 2 Karten ausgewählt" in page
    assert 'name="deck" required value="EL1"' in page
    assert "neue APKG-Datei" in page


def test_edit_and_save_card(auth_client: TestClient) -> None:
    """Editing returns a form; saving shows the new content and the counter.

    Args:
        auth_client: Logged-in test client.
    """
    job_id = done_job(auth_client)

    form = auth_client.get(f"/jobs/{job_id}/cards/c2/edit").text
    saved = auth_client.post(
        f"/jobs/{job_id}/cards/c2",
        data={
            "front": "Was ist ein Volt?",
            "back": "SI-Einheit",
            "tags": "SI Einheit",
            "subdeck": "Grundlagen",
        },
    )

    assert '<textarea name="front"' in form and "Was ist Volt?" in form
    assert saved.status_code == 200
    assert "Was ist ein Volt?" in saved.text
    assert 'id="review-count" hx-swap-oob="true"' in saved.text
    assert "Tags: SI Einheit" in saved.text


def test_invalid_edit_returns_form_with_reason(auth_client: TestClient) -> None:
    """A refused edit keeps the entered values and explains why, with status 200.

    Args:
        auth_client: Logged-in test client.
    """
    job_id = done_job(auth_client)

    response = auth_client.post(
        f"/jobs/{job_id}/cards/c1",
        data={"front": "", "back": "Neue Antwort", "tags": "", "subdeck": ""},
    )

    assert response.status_code == 200
    assert "Frage darf nicht leer sein" in response.text
    assert "Neue Antwort" in response.text
    assert "Was ist Ohm?" in auth_client.get(f"/jobs/{job_id}").text


def test_deselect_and_delete_update_counter(auth_client: TestClient) -> None:
    """Deselecting and deleting change what will be written.

    Args:
        auth_client: Logged-in test client.
    """
    job_id = done_job(auth_client)

    deselected = auth_client.post(f"/jobs/{job_id}/cards/c1/select", data={})
    deleted = auth_client.post(f"/jobs/{job_id}/cards/c2/delete")

    assert "review-card deselected" in deselected.text
    assert "1 von 2 Karten ausgewählt" in deselected.text
    assert "review-card" not in deleted.text
    assert "0 von 1 Karten ausgewählt" in deleted.text
    assert "Was ist Volt?" not in auth_client.get(f"/jobs/{job_id}").text


def test_write_shows_result_and_downloads(auth_client: TestClient) -> None:
    """Writing creates the APKG, shows the result, and enables the downloads.

    Args:
        auth_client: Logged-in test client.
    """
    job_id = done_job(auth_client, source_text=True)

    response = auth_client.post(
        f"/jobs/{job_id}/write", data={"deck": "EL1"}, follow_redirects=False
    )

    assert response.headers["location"] == f"/jobs/{job_id}#result"
    page = auth_client.get(f"/jobs/{job_id}").text
    assert "2 neue Karten geschrieben" in page
    assert "EL1::Grundlagen" in page
    assert "Karten prüfen" not in page
    package = auth_client.get(f"/jobs/{job_id}/files/apkg")
    assert 'filename="EL1.apkg"' in package.headers["content-disposition"]
    assert zipfile.ZipFile(io.BytesIO(package.content)).namelist()
    cards = auth_client.get(f"/jobs/{job_id}/files/json").json()
    assert [card["front"] for card in cards["cards"]] == ["Was ist Ohm?", "Was ist Volt?"]
    assert auth_client.get(f"/jobs/{job_id}/files/source").text.startswith("[Seite 1]")


def test_changes_after_writing_are_refused(auth_client: TestClient) -> None:
    """Once written, the review cannot change and nothing is written twice.

    Args:
        auth_client: Logged-in test client.
    """
    job_id = done_job(auth_client)
    auth_client.post(f"/jobs/{job_id}/write", data={"deck": "EL1"})

    assert auth_client.post(f"/jobs/{job_id}/cards/c1/select", data={}).status_code == 409
    assert auth_client.post(f"/jobs/{job_id}/write", data={"deck": "EL1"}).status_code == 400


def test_invalid_deck_keeps_entry(auth_client: TestClient) -> None:
    """A deck with an empty level is refused with the entered value kept.

    Args:
        auth_client: Logged-in test client.
    """
    job_id = done_job(auth_client)

    response = auth_client.post(f"/jobs/{job_id}/write", data={"deck": "EL1::"})

    assert response.status_code == 400
    assert "leerer Ebene" in response.text
    assert 'value="EL1::"' in response.text


def test_json_download_before_writing(auth_client: TestClient) -> None:
    """The selection can be downloaded as card JSON before writing.

    Args:
        auth_client: Logged-in test client.
    """
    job_id = done_job(auth_client)
    auth_client.post(f"/jobs/{job_id}/cards/c2/select", data={})

    response = auth_client.get(f"/jobs/{job_id}/files/json")

    assert 'filename="EL1.cards.json"' in response.headers["content-disposition"]
    assert [card["front"] for card in json.loads(response.content)["cards"]] == ["Was ist Ohm?"]


@pytest.mark.parametrize("kind", ["apkg", "source", "unbekannt"])
def test_missing_files_are_404(auth_client: TestClient, kind: str) -> None:
    """Unwritten APKGs, absent source texts, and unknown kinds answer 404.

    Args:
        auth_client: Logged-in test client.
        kind: Requested download.
    """
    job_id = done_job(auth_client)

    assert auth_client.get(f"/jobs/{job_id}/files/{kind}").status_code == 404


def test_review_needs_finished_job(auth_client: TestClient) -> None:
    """Cards of unknown or unfinished jobs are not reachable.

    Args:
        auth_client: Logged-in test client.
    """
    store = auth_client.app.state.jobs
    job = store.create(io.BytesIO(b"# T"), "wartet.md", 3, {"form": {}, "target_file": None})

    assert auth_client.get(f"/jobs/{job.id}/cards/c1/edit").status_code == 404
    assert auth_client.get("/jobs/" + "0" * 32 + "/files/json").status_code == 404


def test_review_needs_login(client: TestClient) -> None:
    """Anonymous requests cannot change or download cards.

    Args:
        client: Anonymous test client.
    """
    job_id = done_job(client)

    assert client.post(f"/jobs/{job_id}/cards/c1/delete", follow_redirects=False).status_code == 303
    assert client.get(f"/jobs/{job_id}/files/json", follow_redirects=False).status_code == 303
