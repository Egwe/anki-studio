"""Tests for APKG deck inspection and card-JSON export (AS-007, AS-008)."""

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from anki_flashcards.apkg import create_apkg, inspect_apkg
from anki_flashcards.errors import FlashcardError
from anki_flashcards.models import Card, save_cards
from fastapi.testclient import TestClient

from anki_studio.card_export import EXPORT_FILE, EXPORT_KIND, ExportRunner
from anki_studio.decks import DECKS_KIND, DecksRunner, deck_tree, inspect_decks, load_decks
from anki_studio.jobs import JobStatus, JobStore
from anki_studio.settings import StudioSettings
from anki_studio.uploads import APKG, CARD_JSON
from tests.conftest import wait_until

CARDS = [
    Card(front="Was ist Ohm?", back="Einheit des Widerstands", subdeck="Grundlagen"),
    Card(front="Was ist Volt?", back="Einheit der Spannung"),
]


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    """Provide an empty job store.

    Args:
        tmp_path: Temporary test directory.

    Returns:
        Job store below the temporary directory.
    """
    return JobStore(tmp_path / "jobs")


def package(path: Path) -> Path:
    """Create one APKG with a parent deck and a child deck.

    Args:
        path: Destination of the new APKG.

    Returns:
        The supplied package path after creation.
    """
    create_apkg(path, "Elektrotechnik", CARDS)
    return path


def cards_json(path: Path) -> Path:
    """Write version-1 card JSON for the export runner.

    Args:
        path: Destination JSON file.

    Returns:
        The supplied JSON path after writing.
    """
    save_cards(path, CARDS, deck="Elektrotechnik", source="test.md")
    return path


def test_inspect_decks_builds_a_nested_tree(tmp_path: Path) -> None:
    """An APKG's direct counts appear at the matching tree levels.

    Args:
        tmp_path: Temporary directory for the APKG.
    """
    tree = inspect_decks(package(tmp_path / "elektrotechnik.apkg"))
    parent = next(node for node in tree if node.full_name == "Elektrotechnik")

    assert parent.cards == 1
    assert [(child.full_name, child.cards) for child in parent.children] == [
        ("Elektrotechnik::Grundlagen", 1)
    ]


def test_deck_tree_accepts_open_collection_entries() -> None:
    """The common tree builder keeps collection direct counts and parents.

    Returns:
        None.
    """
    tree = deck_tree(
        [
            {"name": "Elektrotechnik::Grundlagen", "cards": 3},
            {"name": "Mathematik", "cards": 2},
        ]
    )

    assert [(deck.full_name, deck.cards) for deck in tree] == [
        ("Elektrotechnik", 0),
        ("Mathematik", 2),
    ]
    assert tree[0].children[0].cards == 3


def test_deck_runner_stores_the_inspection_result(store: JobStore, tmp_path: Path) -> None:
    """The serial deck runner preserves the tree for the result page.

    Args:
        store: Empty job store.
        tmp_path: Temporary directory for the source APKG.
    """
    source = package(tmp_path / "elektrotechnik.apkg")
    with source.open("rb") as stream:
        job = store.create(
            stream,
            source.name,
            source.stat().st_size,
            {"kind": DECKS_KIND},
            upload_kind=APKG,
        )

    notices: list[dict[str, Any]] = []
    DecksRunner(store)(job, notices.append, lambda: False)

    tree = load_decks(store.job_dir(job.id) / "decks.json")
    assert any(node.full_name == "Elektrotechnik" for node in tree)
    assert notices[-1]["text"].endswith("Decks der obersten Ebene gefunden.")


def test_export_runner_creates_new_apkg(
    store: JobStore, studio_settings: StudioSettings, tmp_path: Path
) -> None:
    """The runner delegates JSON validation and new-package creation to the generator.

    Args:
        store: Empty job store.
        studio_settings: Generator configuration path for the runner.
        tmp_path: Temporary directory for the source JSON.
    """
    source = cards_json(tmp_path / "karten.cards.json")
    with source.open("rb") as stream:
        job = store.create(
            stream,
            source.name,
            source.stat().st_size,
            {"kind": EXPORT_KIND, "deck": "Export::EL1"},
            upload_kind=CARD_JSON,
        )

    notices: list[dict[str, Any]] = []
    ExportRunner(store, studio_settings.generator_path)(job, notices.append, lambda: False)

    output = store.job_dir(job.id) / EXPORT_FILE
    names = {deck["name"] for deck in inspect_apkg(output)}
    assert {"Export::EL1", "Export::EL1::Grundlagen"} <= names
    assert notices[-1]["text"] == "2 Karten für Deck „Export::EL1“ geschrieben."


def test_export_runner_refuses_invalid_card_json(
    store: JobStore, studio_settings: StudioSettings
) -> None:
    """Invalid versioned JSON cannot create an APKG.

    Args:
        store: Empty job store.
        studio_settings: Generator configuration path for the runner.
    """
    job = store.create(
        io.BytesIO(b'{"schema_version": 2, "cards": []}'),
        "karten.cards.json",
        35,
        {"kind": EXPORT_KIND, "deck": "Export"},
        upload_kind=CARD_JSON,
    )

    with pytest.raises(FlashcardError, match="Unsupported card JSON schema"):
        ExportRunner(store, studio_settings.generator_path)(job, lambda event: None, lambda: False)

    assert not (store.job_dir(job.id) / EXPORT_FILE).exists()


def test_decks_page_queues_job_and_shows_result(auth_client: TestClient, tmp_path: Path) -> None:
    """The page stores an APKG, reports progress, and renders its tree.

    Args:
        auth_client: Logged-in application client.
        tmp_path: Temporary directory for the upload APKG.
    """
    source = package(tmp_path / "elektrotechnik.apkg")
    with source.open("rb") as stream:
        response = auth_client.post(
            "/decks",
            files={"package": (source.name, stream, "application/octet-stream")},
            follow_redirects=False,
        )

    job_id = response.headers["location"].rsplit("/", 1)[-1]
    store = auth_client.app.state.jobs
    wait_until(lambda: store.get(job_id).status is JobStatus.DONE)
    job_page = auth_client.get(f"/jobs/{job_id}").text
    result = auth_client.get(f"/decks/jobs/{job_id}")

    assert response.status_code == 303
    assert "Deckbaum bereit" in job_page
    assert "Elektrotechnik" in result.text and "Grundlagen" in result.text


def test_decks_page_refuses_a_non_apkg_upload(auth_client: TestClient) -> None:
    """The deck form rejects upload types before a job is created.

    Args:
        auth_client: Logged-in application client.
    """
    response = auth_client.post(
        "/decks",
        files={"package": ("notizen.md", io.BytesIO(b"# Notizen"), "text/markdown")},
    )

    assert response.status_code == 400
    assert "wird nicht unterstützt" in response.text
    assert auth_client.app.state.jobs.list_jobs() == []


def test_decks_page_explains_that_collection_sync_is_needed(auth_client: TestClient) -> None:
    """An untouched local collection is not presented as a deck source.

    Args:
        auth_client: Logged-in client without configured sync state.
    """
    response = auth_client.get("/decks")

    assert response.status_code == 200
    assert "Synchronisierte Sammlung" in response.text
    assert "Noch nicht synchronisiert" in response.text


def test_export_page_queues_new_apkg_and_downloads_it(auth_client: TestClient) -> None:
    """The export page writes an uploaded card JSON into a downloadable APKG.

    Args:
        auth_client: Logged-in application client.
    """
    payload = json.dumps(
        {
            "schema_version": 1,
            "deck": "ignored",
            "cards": [card.model_dump(exclude_none=True) for card in CARDS],
        }
    ).encode()
    response = auth_client.post(
        "/export",
        data={"deck": "Export::EL1"},
        files={"cards": ("karten.cards.json", io.BytesIO(payload), "application/json")},
        follow_redirects=False,
    )

    job_id = response.headers["location"].rsplit("/", 1)[-1]
    store = auth_client.app.state.jobs
    wait_until(lambda: store.get(job_id).status is JobStatus.DONE)
    job_page = auth_client.get(f"/jobs/{job_id}").text
    download = auth_client.get(f"/export/jobs/{job_id}/file")

    assert response.status_code == 303
    assert "APKG bereit" in job_page
    assert "filename*=utf-8''Export%20-%20EL1.apkg" in download.headers["content-disposition"]
    assert zipfile.ZipFile(io.BytesIO(download.content)).namelist()


@pytest.mark.parametrize(
    ("data", "files", "message"),
    [
        ({}, {}, "Bitte eine Karten-JSON-Datei auswählen"),
        (
            {"deck": "A::"},
            {"cards": ("karten.json", io.BytesIO(b"{}"), "application/json")},
            "leerer Ebene",
        ),
        (
            {"deck": "Export"},
            {"cards": ("karten.txt", io.BytesIO(b"{}"), "text/plain")},
            "wird nicht unterstützt",
        ),
    ],
)
def test_export_page_refuses_invalid_submissions(
    auth_client: TestClient, data: dict[str, str], files: dict[str, Any], message: str
) -> None:
    """Missing files, malformed deck names, and wrong types create no export job.

    Args:
        auth_client: Logged-in application client.
        data: Text fields of the export form.
        files: File fields of the export form.
        message: Expected error message fragment.
    """
    response = auth_client.post("/export", data=data, files=files)

    assert response.status_code == 400
    assert message in response.text
    assert auth_client.app.state.jobs.list_jobs() == []


def test_decks_and_export_need_login(client: TestClient) -> None:
    """Anonymous requests cannot create APKG inspection or export jobs.

    Args:
        client: Anonymous application client.
    """
    decks = client.post(
        "/decks",
        files={"package": ("deck.apkg", io.BytesIO(b"PK"), "application/octet-stream")},
        follow_redirects=False,
    )
    export = client.post(
        "/export",
        data={"deck": "Export"},
        files={"cards": ("karten.json", io.BytesIO(b"{}"), "application/json")},
        follow_redirects=False,
    )

    assert decks.headers["location"] == "/login"
    assert export.headers["location"] == "/login"
    assert client.app.state.jobs.list_jobs() == []
