"""Review generated cards and write the selection into an APKG (AS-005, AS-006).

``cards.json`` stays the generator's original output. The review state
lives in ``review.json`` in the job folder: every card gets a stable id and
a selection flag. Every change is validated by the generator's ``Card``;
writing deduplicates with ``deduplicate_cards`` and uses ``write_apkg``.
``result.json`` records the outcome and prevents writing twice.
"""

import json
import os
import tempfile
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anki_flashcards.apkg import ExportResult
from anki_flashcards.models import Card, deduplicate_cards, load_cards, save_cards
from anki_flashcards.pipeline import validate_output, write_apkg
from pydantic import ValidationError

from anki_studio.forms import normalize_deck
from anki_studio.generation import CARDS_FILE, job_paths
from anki_studio.jobs import Job, JobStore

REVIEW_FILE = "review.json"
RESULT_FILE = "result.json"
EXPORT_FILE = "karten.cards.json"
WRITING_FILE = "writing.json"

_LOCK = threading.Lock()


class ReviewError(ValueError):
    """Report a refused review change in words for the user."""


class UnknownCardError(ReviewError):
    """Report a card identifier that the review does not contain."""


class AlreadyWrittenError(ReviewError):
    """Report a change after the cards were written."""


class AlreadyWritingError(AlreadyWrittenError):
    """Report a change while a queued collection write owns the review."""


@dataclass(frozen=True)
class ReviewCard:
    """One card under review.

    Attributes:
        id: Stable identifier such as ``c3``.
        card: Validated card of the generator.
        selected: Whether the card will be written.
    """

    id: str
    card: Card
    selected: bool = True


@dataclass(frozen=True)
class Review:
    """The review state of one job.

    Attributes:
        deck: Target deck stored by the generation run.
        cards: Cards in their original order.
    """

    deck: str
    cards: list[ReviewCard]

    @property
    def selected(self) -> list[Card]:
        """Return the selected cards without duplicates.

        Returns:
            Cards that would be written, deduplicated by the generator.
        """
        return deduplicate_cards([entry.card for entry in self.cards if entry.selected])


@dataclass(frozen=True)
class PendingCollectionWrite:
    """Reserve one immutable review selection for a collection-write job.

    Attributes:
        job_id: Identifier of the dedicated collection-write job.
        deck: Normalized target deck fixed for that job.
    """

    job_id: str
    deck: str


def has_cards(store: JobStore, job: Job) -> bool:
    """Tell whether a job produced cards that can be reviewed.

    Args:
        store: Job store.
        job: Job to check.

    Returns:
        True if ``cards.json`` exists.
    """
    return (store.job_dir(job.id) / CARDS_FILE).exists()


def load_review(store: JobStore, job: Job) -> Review:
    """Read the review state, creating it from ``cards.json`` on first use.

    Args:
        store: Job store.
        job: Job with generated cards.

    Returns:
        The review state.

    Raises:
        FlashcardError: If ``cards.json`` cannot be read.
    """
    folder = store.job_dir(job.id)
    with _LOCK:
        return _load(folder)


def update_card(store: JobStore, job: Job, card_id: str, fields: dict[str, str]) -> ReviewCard:
    """Replace the content of one card after validating it.

    Args:
        store: Job store.
        job: Job under review.
        card_id: Identifier of the card.
        fields: ``front``, ``back``, ``tags`` (separated by spaces) and
            ``subdeck`` (empty for none) as entered.

    Returns:
        The updated card.

    Raises:
        ReviewError: If the card is unknown, the job is already written, or
            the generator's validation refuses the content.
    """
    card = _validated_card(fields)
    return _change(store, job, card_id, lambda entry: ReviewCard(entry.id, card, entry.selected))


def set_selected(store: JobStore, job: Job, card_id: str, selected: bool) -> ReviewCard:
    """Select or deselect one card for writing.

    Args:
        store: Job store.
        job: Job under review.
        card_id: Identifier of the card.
        selected: New selection state.

    Returns:
        The updated card.

    Raises:
        ReviewError: If the card is unknown or the job is already written.
    """
    return _change(store, job, card_id, lambda entry: ReviewCard(entry.id, entry.card, selected))


def delete_card(store: JobStore, job: Job, card_id: str) -> None:
    """Remove one card from the review.

    Args:
        store: Job store.
        job: Job under review.
        card_id: Identifier of the card.

    Returns:
        None.

    Raises:
        ReviewError: If the card is unknown or the job is already written.
    """
    folder = store.job_dir(job.id)
    with _LOCK:
        _refuse_written(folder)
        review = _load(folder)
        remaining = [entry for entry in review.cards if entry.id != card_id]
        if len(remaining) == len(review.cards):
            raise UnknownCardError("Diese Karte gibt es nicht.")
        _save(folder, Review(review.deck, remaining))


def write_reviewed(store: JobStore, job: Job, deck: str) -> dict[str, Any]:
    """Write the selected cards into the job's APKG target once.

    Args:
        store: Job store.
        job: Job under review.
        deck: Target deck; ``::`` separates subdeck levels.

    Returns:
        The stored result: ``deck``, ``added``, ``skipped``,
        ``added_by_deck``, ``file`` and ``written_at``.

    Raises:
        ReviewError: If nothing is selected, the deck name is invalid, or
            the job was already written.
        FlashcardError: If the APKG target is invalid or writing fails.
    """
    folder = store.job_dir(job.id)
    paths = job_paths(store, job)
    with _LOCK:
        _refuse_written(folder)
        cards = _load(folder).selected
        if not cards:
            raise ReviewError("Keine Karte ausgewählt.")
        target_deck = _deck(deck)
        validate_output(paths.output, paths.extend)
        export = write_apkg(paths.output, target_deck, cards, paths.extend)
        save_cards(folder / EXPORT_FILE, cards, deck=target_deck, source=job.source_name)
        result = _result(export, paths.output)
        _write_json(folder / RESULT_FILE, result)
    return result


def reserve_collection_write(
    store: JobStore, job: Job, write_job_id: str, deck: str
) -> PendingCollectionWrite:
    """Freeze the selected cards for one queued collection write.

    The reservation prevents edits, deselection, and a second write button
    from changing the review while its background job is waiting or running.

    Args:
        store: Job store containing the source generation job.
        job: Finished generation job whose review is written.
        write_job_id: Identifier of the new no-upload write job.
        deck: Target deck submitted by the user.

    Returns:
        The persisted reservation with normalized deck name.

    Raises:
        ReviewError: If another write owns the review, no card is selected,
            or the target deck is invalid.
    """
    folder = store.job_dir(job.id)
    with _LOCK:
        _refuse_written(folder)
        cards = _load(folder).selected
        if not cards:
            raise ReviewError("Keine Karte ausgewählt.")
        pending = PendingCollectionWrite(write_job_id, _deck(deck))
        _write_json(folder / WRITING_FILE, {"job_id": pending.job_id, "deck": pending.deck})
    return pending


def reserved_collection_cards(
    store: JobStore, job: Job, write_job_id: str
) -> tuple[str, list[Card]]:
    """Return the frozen selected cards for their collection-write job.

    Args:
        store: Job store containing the source generation job.
        job: Finished generation job with a previous reservation.
        write_job_id: Identifier expected in ``writing.json``.

    Returns:
        Normalized target deck and selected, deduplicated cards.

    Raises:
        ReviewError: If the reservation is gone, belongs to another job, or
            no selected cards remain.
    """
    folder = store.job_dir(job.id)
    with _LOCK:
        pending = _pending(folder)
        if pending is None or pending.job_id != write_job_id:
            raise ReviewError("Der Schreibauftrag gehört nicht mehr zu dieser Kartenprüfung.")
        cards = _load(folder).selected
        if not cards:
            raise ReviewError("Keine Karte ausgewählt.")
        return pending.deck, cards


def finish_collection_write(
    store: JobStore, job: Job, write_job_id: str, result: dict[str, Any]
) -> None:
    """Persist a collection result and unlock its source review.

    Args:
        store: Job store containing the source generation job.
        job: Finished generation job with a reserved collection write.
        write_job_id: Identifier expected in ``writing.json``.
        result: JSON-safe add/skip and sync outcome to expose on the source job.

    Returns:
        None.

    Raises:
        ReviewError: If the reservation belongs to another job or a result is
            already stored.
    """
    folder = store.job_dir(job.id)
    with _LOCK:
        _refuse_written_result(folder)
        pending = _pending(folder)
        if pending is None or pending.job_id != write_job_id:
            raise ReviewError("Der Schreibauftrag gehört nicht mehr zu dieser Kartenprüfung.")
        _write_json(folder / RESULT_FILE, result)
        (folder / WRITING_FILE).unlink(missing_ok=True)


def release_collection_write(store: JobStore, job: Job, write_job_id: str) -> None:
    """Unlock a review after its collection-write job fails or is cancelled.

    Args:
        store: Job store containing the source generation job.
        job: Finished generation job whose reservation may be removed.
        write_job_id: Identifier of the failed or cancelled write job.

    Returns:
        None. A missing or different reservation is left unchanged.
    """
    folder = store.job_dir(job.id)
    with _LOCK:
        pending = _pending(folder)
        if pending is not None and pending.job_id == write_job_id:
            (folder / WRITING_FILE).unlink(missing_ok=True)


def clear_finished_collection_write(store: JobStore, job: Job) -> None:
    """Remove a reservation orphaned by a restart or finished failed job.

    Args:
        store: Job store that can look up the dedicated write job.
        job: Finished generation job whose review might be locked.

    Returns:
        None. A live reservation and a review with a stored result stay.
    """
    folder = store.job_dir(job.id)
    with _LOCK:
        if (folder / RESULT_FILE).exists():
            return
        pending = _pending(folder)
        if pending is None:
            return
        write_job = store.get(pending.job_id)
        if write_job is None or write_job.status.finished:
            (folder / WRITING_FILE).unlink(missing_ok=True)


def pending_collection_write(store: JobStore, job: Job) -> PendingCollectionWrite | None:
    """Return the live collection-write reservation of a review, if any.

    Args:
        store: Job store containing the source generation job.
        job: Finished generation job to inspect.

    Returns:
        Reservation while the separate write job is queued or running, or
        None after completion, failure, or no collection target.
    """
    clear_finished_collection_write(store, job)
    with _LOCK:
        return _pending(store.job_dir(job.id))


def collection_result(export: ExportResult, sync_result: str) -> dict[str, Any]:
    """Build the stored source-job result for a collection write.

    Args:
        export: Add/skip result returned by the generator collection API.
        sync_result: Machine-readable result of the post-write safe sync.

    Returns:
        JSON-safe result that shares the regular review result format.
    """
    return {
        "target": "collection",
        "deck": export.deck,
        "added": export.added,
        "skipped": export.skipped,
        "added_by_deck": export.added_by_deck,
        "sync_result": sync_result,
        "written_at": datetime.now(UTC).isoformat(),
    }


def load_result(store: JobStore, job: Job) -> dict[str, Any] | None:
    """Read the outcome of writing, if the job was written.

    Args:
        store: Job store.
        job: Job to check.

    Returns:
        The stored result, or None.
    """
    path = store.job_dir(job.id) / RESULT_FILE
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def export_json(store: JobStore, job: Job) -> Path:
    """Write the selected cards as version-1 card JSON for download.

    Args:
        store: Job store.
        job: Job under review or written.

    Returns:
        Path of ``karten.cards.json`` in the job folder.

    Raises:
        ReviewError: If no card is selected.
    """
    folder = store.job_dir(job.id)
    with _LOCK:
        review = _load(folder)
        cards = review.selected
        if not cards:
            raise ReviewError("Keine Karte ausgewählt.")
        if not (folder / RESULT_FILE).exists():
            save_cards(folder / EXPORT_FILE, cards, deck=review.deck, source=job.source_name)
    return folder / EXPORT_FILE


def _change(
    store: JobStore, job: Job, card_id: str, change: Callable[[ReviewCard], ReviewCard]
) -> ReviewCard:
    """Apply a change to one card and save the review.

    Args:
        store: Job store.
        job: Job under review.
        card_id: Identifier of the card.
        change: Function from the old to the new ``ReviewCard``.

    Returns:
        The changed card.

    Raises:
        ReviewError: If the card is unknown or the job is already written.
    """
    folder = store.job_dir(job.id)
    with _LOCK:
        _refuse_written(folder)
        review = _load(folder)
        cards = list(review.cards)
        index = next((i for i, entry in enumerate(cards) if entry.id == card_id), None)
        if index is None:
            raise UnknownCardError("Diese Karte gibt es nicht.")
        cards[index] = change(cards[index])
        _save(folder, Review(review.deck, cards))
        return cards[index]


def _validated_card(fields: dict[str, str]) -> Card:
    """Build a card from entered fields with the generator's validation.

    Args:
        fields: ``front``, ``back``, ``tags`` and ``subdeck`` as entered.

    Returns:
        The validated card.

    Raises:
        ReviewError: With the generator's reason, in one line.
    """
    data = {
        "front": fields.get("front", ""),
        "back": fields.get("back", ""),
        "tags": fields.get("tags", "").split(),
        "subdeck": fields.get("subdeck", "").strip() or None,
    }
    try:
        return Card.model_validate(data)
    except ValidationError as error:
        raise ReviewError("; ".join(_reason(item) for item in error.errors())) from error


def _reason(item: dict[str, Any]) -> str:
    """Translate one validation error of a card into German.

    Args:
        item: One entry of ``ValidationError.errors()``.

    Returns:
        Field name and message.
    """
    names = {"front": "Frage", "back": "Antwort", "tags": "Tags", "subdeck": "Unterdeck"}
    field = names.get(str(item["loc"][0]), str(item["loc"][0])) if item["loc"] else "Karte"
    messages = {
        "string_too_short": "darf nicht leer sein",
        "string_too_long": f"ist zu lang (höchstens {item.get('ctx', {}).get('max_length')})",
        "too_long": "hat zu viele Einträge",
    }
    return f"{field} {messages.get(item['type'], item['msg'])}"


def _deck(deck: str) -> str:
    """Validate the target deck chosen for writing.

    Args:
        deck: Entered deck name.

    Returns:
        The normalized deck name.

    Raises:
        ReviewError: If the name is empty or has an empty level.
    """
    try:
        return normalize_deck(deck.strip())
    except ValueError as error:
        raise ReviewError(str(error)) from error


def _result(export: ExportResult, output: Path) -> dict[str, Any]:
    """Turn the generator's export result into storable data.

    Args:
        export: Result of ``write_apkg``.
        output: Written APKG.

    Returns:
        JSON-safe result for ``result.json``.
    """
    return {
        "deck": export.deck,
        "added": export.added,
        "skipped": export.skipped,
        "added_by_deck": export.added_by_deck,
        "file": output.name,
        "written_at": datetime.now(UTC).isoformat(),
    }


def _refuse_written(folder: Path) -> None:
    """Refuse changes once the cards were written.

    Args:
        folder: Job folder.

    Returns:
        None.

    Raises:
        ReviewError: If ``result.json`` exists.
    """
    _refuse_written_result(folder)
    if (folder / WRITING_FILE).exists():
        raise AlreadyWritingError("Die Karten werden bereits in die Sammlung geschrieben.")


def _refuse_written_result(folder: Path) -> None:
    """Refuse a second final result without considering a live reservation.

    Args:
        folder: Job folder containing ``result.json`` when the review ended.

    Returns:
        None.

    Raises:
        AlreadyWrittenError: If ``result.json`` exists.
    """
    if (folder / RESULT_FILE).exists():
        raise AlreadyWrittenError("Die Karten wurden bereits geschrieben.")


def _pending(folder: Path) -> PendingCollectionWrite | None:
    """Read a collection-write reservation while the review lock is held.

    Args:
        folder: Job folder containing an optional ``writing.json`` file.

    Returns:
        Stored reservation, or None when no reservation exists.

    Raises:
        ReviewError: If the reservation file has an invalid shape.
    """
    path = folder / WRITING_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        job_id = data["job_id"]
        deck = data["deck"]
    except (OSError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise ReviewError("Der Schreibauftrag ist nicht lesbar.") from error
    if not isinstance(job_id, str) or not isinstance(deck, str):
        raise ReviewError("Der Schreibauftrag ist nicht lesbar.")
    return PendingCollectionWrite(job_id, deck)


def _load(folder: Path) -> Review:
    """Read ``review.json`` or create it from ``cards.json``.

    Args:
        folder: Job folder; the caller holds the lock.

    Returns:
        The review state.

    Raises:
        FlashcardError: If ``cards.json`` cannot be read.
    """
    path = folder / REVIEW_FILE
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        cards = [
            ReviewCard(entry["id"], Card.model_validate(entry["card"]), entry["selected"])
            for entry in data["cards"]
        ]
        return Review(data["deck"], cards)
    deck = json.loads((folder / CARDS_FILE).read_text(encoding="utf-8")).get("deck", "")
    cards = [
        ReviewCard(f"c{index}", card)
        for index, card in enumerate(load_cards(folder / CARDS_FILE), 1)
    ]
    review = Review(deck, cards)
    _save(folder, review)
    return review


def _save(folder: Path, review: Review) -> None:
    """Store the review state atomically.

    Args:
        folder: Job folder.
        review: State to store.

    Returns:
        None.
    """
    data = {
        "deck": review.deck,
        "cards": [
            {"id": entry.id, "card": entry.card.model_dump(), "selected": entry.selected}
            for entry in review.cards
        ],
    }
    _write_json(folder / REVIEW_FILE, data)


def _write_json(path: Path, data: Any) -> None:
    """Write JSON next to its destination and replace it atomically.

    Args:
        path: Destination file.
        data: JSON-safe content.

    Returns:
        None.
    """
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as temporary:
        json.dump(data, temporary, ensure_ascii=False, indent=2)
    os.replace(temporary.name, path)
