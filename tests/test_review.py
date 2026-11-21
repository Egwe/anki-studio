"""Tests for reviewing and writing generated cards (AS-005, AS-006)."""

import io
import json
from pathlib import Path

import pytest
from anki_flashcards.apkg import ExportResult, create_apkg, inspect_apkg
from anki_flashcards.errors import FlashcardError
from anki_flashcards.models import Card, load_cards, save_cards

from anki_studio.forms import GenerateForm
from anki_studio.generation import CARDS_FILE, NEW_APKG_FILE, TARGET_DIR, job_options
from anki_studio.jobs import Job, JobStatus, JobStore
from anki_studio.review import (
    EXPORT_FILE,
    AlreadyWritingError,
    ReviewError,
    collection_result,
    delete_card,
    export_json,
    finish_collection_write,
    load_result,
    load_review,
    pending_collection_write,
    reserve_collection_write,
    reserved_collection_cards,
    set_selected,
    update_card,
    write_reviewed,
)
from anki_studio.uploads import APKG

CARDS = [
    Card(front="Was ist Ohm?", back="Einheit des Widerstands", tags=["Ohm"], subdeck="Grundlagen"),
    Card(front="Was ist Volt?", back="Einheit der Spannung"),
    Card(front="Was ist Ampere?", back="Einheit des Stroms"),
]


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    """Provide an empty job store.

    Args:
        tmp_path: Temporary test folder.

    Returns:
        A store rooted at ``<tmp_path>/jobs``.
    """
    return JobStore(tmp_path / "jobs")


def done_job(store: JobStore, target_file: str | None = None) -> Job:
    """Create a finished job whose run saved three cards for deck EL1.

    Args:
        store: Job store.
        target_file: Name of an APKG to extend, or None for a new APKG.

    Returns:
        The finished job.
    """
    options = job_options(GenerateForm.model_validate({"deck": "EL1"}), target_file)
    job = store.create(io.BytesIO(b"# T"), "skript.md", 3, options)
    save_cards(store.job_dir(job.id) / CARDS_FILE, CARDS, deck="EL1", source="skript.md")
    return store.update(job.id, JobStatus.DONE)


def test_review_starts_with_all_cards_selected(store: JobStore) -> None:
    """The first review lists every generated card with a stable id.

    Args:
        store: Job store.
    """
    review = load_review(store, done_job(store))

    assert review.deck == "EL1"
    assert [entry.id for entry in review.cards] == ["c1", "c2", "c3"]
    assert all(entry.selected for entry in review.cards)
    assert review.selected == CARDS


def test_edit_is_validated_and_kept(store: JobStore) -> None:
    """Edits pass the generator's Card validation and survive a reload.

    Args:
        store: Job store.
    """
    job = done_job(store)

    updated = update_card(
        store,
        job,
        "c2",
        {
            "front": " Was ist Volt? ",
            "back": "SI-Einheit der Spannung",
            "tags": "Einheit  SI",
            "subdeck": "",
        },
    )

    assert updated.card == Card(
        front="Was ist Volt?", back="SI-Einheit der Spannung", tags=["Einheit", "SI"]
    )
    assert load_review(store, job).cards[1].card.back == "SI-Einheit der Spannung"
    assert load_cards(store.job_dir(job.id) / CARDS_FILE) == CARDS


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"front": "", "back": "x"}, "Frage darf nicht leer sein"),
        ({"front": "x", "back": ""}, "Antwort darf nicht leer sein"),
        ({"front": "x" * 2001, "back": "x"}, "Frage ist zu lang"),
        ({"front": "x", "back": "y", "subdeck": "A::B"}, "Unterdeck"),
        ({"front": "x", "back": "y", "tags": " ".join(f"t{i}" for i in range(21))}, "Tags"),
    ],
)
def test_invalid_edits_are_refused(store: JobStore, fields: dict[str, str], message: str) -> None:
    """Invalid content is refused with a German reason and nothing changes.

    Args:
        store: Job store.
        fields: Entered fields.
        message: Expected part of the reason.
    """
    job = done_job(store)

    with pytest.raises(ReviewError, match=message):
        update_card(store, job, "c1", fields)

    assert load_review(store, job).cards[0].card == CARDS[0]


def test_deselect_and_delete(store: JobStore) -> None:
    """Deselected and deleted cards are not written.

    Args:
        store: Job store.
    """
    job = done_job(store)

    set_selected(store, job, "c1", False)
    delete_card(store, job, "c3")

    review = load_review(store, job)
    assert [entry.id for entry in review.cards] == ["c1", "c2"]
    assert review.selected == [CARDS[1]]
    with pytest.raises(ReviewError, match="gibt es nicht"):
        delete_card(store, job, "c3")


def test_write_new_apkg_and_record_result(store: JobStore) -> None:
    """Writing creates the APKG once, records the result, and locks the review.

    Args:
        store: Job store.
    """
    job = done_job(store)
    set_selected(store, job, "c3", False)

    result = write_reviewed(store, job, " Elektrotechnik :: EL1 ")

    package = store.job_dir(job.id) / NEW_APKG_FILE
    assert result["added"] == 2
    assert result["deck"] == "Elektrotechnik::EL1"
    assert result["added_by_deck"] == {
        "Elektrotechnik::EL1::Grundlagen": 1,
        "Elektrotechnik::EL1": 1,
    }
    assert load_result(store, job) == result
    assert {deck["name"] for deck in inspect_apkg(package)} >= {
        "Elektrotechnik::EL1",
        "Elektrotechnik::EL1::Grundlagen",
    }
    assert len(load_cards(store.job_dir(job.id) / EXPORT_FILE)) == 2
    with pytest.raises(ReviewError, match="bereits geschrieben"):
        write_reviewed(store, job, "EL1")
    with pytest.raises(ReviewError, match="bereits geschrieben"):
        set_selected(store, job, "c1", False)


def test_extend_uploaded_apkg_skips_duplicates(store: JobStore, tmp_path: Path) -> None:
    """Extending an uploaded package adds new cards and skips known ones.

    Args:
        store: Job store.
        tmp_path: Temporary test folder.
    """
    package = tmp_path / "el1.apkg"
    create_apkg(package, "EL1", [Card(front="Was ist Volt?", back="alt")])
    job = done_job(store, "el1.apkg")
    with package.open("rb") as source:
        store.add_file(job.id, TARGET_DIR, source, "el1.apkg", package.stat().st_size, APKG)

    result = write_reviewed(store, job, "EL1")

    assert (result["added"], result["skipped"]) == (2, 1)
    assert result["file"] == "el1.apkg"


@pytest.mark.parametrize("deck", ["", "  ", "A::::B"])
def test_invalid_deck_is_refused(store: JobStore, deck: str) -> None:
    """Empty decks and empty levels are refused before anything is written.

    Args:
        store: Job store.
        deck: Entered deck name.
    """
    job = done_job(store)

    with pytest.raises(ReviewError, match="leerer Ebene"):
        write_reviewed(store, job, deck)

    assert load_result(store, job) is None


def test_nothing_selected_is_refused(store: JobStore) -> None:
    """Without a selected card nothing is written or exported.

    Args:
        store: Job store.
    """
    job = done_job(store)
    for card_id in ("c1", "c2", "c3"):
        set_selected(store, job, card_id, False)

    with pytest.raises(ReviewError, match="Keine Karte ausgewählt"):
        write_reviewed(store, job, "EL1")
    with pytest.raises(ReviewError, match="Keine Karte ausgewählt"):
        export_json(store, job)


def test_export_json_contains_the_selection(store: JobStore) -> None:
    """The JSON download holds the selected, edited cards in the generator format.

    Args:
        store: Job store.
    """
    job = done_job(store)
    set_selected(store, job, "c2", False)

    path = export_json(store, job)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["deck"] == "EL1"
    assert [card["front"] for card in data["cards"]] == ["Was ist Ohm?", "Was ist Ampere?"]


def test_existing_target_blocks_new_apkg(store: JobStore) -> None:
    """A new APKG is never written over an existing file.

    Args:
        store: Job store.
    """
    job = done_job(store)
    (store.job_dir(job.id) / NEW_APKG_FILE).write_bytes(b"x")

    with pytest.raises(FlashcardError, match="already exists"):
        write_reviewed(store, job, "EL1")


def test_collection_reservation_freezes_review_and_stores_result(store: JobStore) -> None:
    """A collection task owns exactly one immutable review until it finishes.

    Args:
        store: Empty job storage.
    """
    job = done_job(store)
    task = store.create_task("Sammlung", {"kind": "collection_write"})

    reservation = reserve_collection_write(store, job, task.id, "Elektrotechnik :: EL1")

    assert reservation.deck == "Elektrotechnik::EL1"
    assert pending_collection_write(store, job) == reservation
    with pytest.raises(AlreadyWritingError, match="bereits in die Sammlung"):
        set_selected(store, job, "c1", False)
    deck, cards = reserved_collection_cards(store, job, task.id)
    assert deck == "Elektrotechnik::EL1"
    assert cards == CARDS
    finish_collection_write(
        store,
        job,
        task.id,
        collection_result(
            ExportResult(Path("collection.anki2"), deck, 3, 0),
            "no_changes",
        ),
    )

    assert pending_collection_write(store, job) is None
    assert load_result(store, job)["target"] == "collection"
