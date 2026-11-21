"""Inspect uploaded APKG files and keep their deck tree as a job result (AS-007)."""

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anki_flashcards.apkg import inspect_apkg

from anki_studio.i18n import translate_with_fallback
from anki_studio.jobs import Job, JobStore
from anki_studio.worker import CancelCheck, Reporter

DECKS_KIND = "decks"
DECKS_FILE = "decks.json"


@dataclass(frozen=True)
class DeckNode:
    """Represent one deck in a nested APKG deck tree.

    Attributes:
        name: Final segment of the deck name, for example ``Kapitel 1``.
        full_name: Complete Anki deck name, for example ``EL1::Kapitel 1``.
        cards: Number of cards directly in this deck, without descendants.
        children: Direct child decks in case-insensitive name order.
    """

    name: str
    full_name: str
    cards: int
    children: tuple["DeckNode", ...]


def inspect_decks(package: Path) -> tuple[DeckNode, ...]:
    """Read an APKG and return its normal decks as a tree.

    Args:
        package: Existing classic or zstd-compressed APKG file.

    Returns:
        Top-level deck nodes with direct card counts.

    Raises:
        FlashcardError: If the package cannot be inspected by the generator.
    """
    return deck_tree(inspect_apkg(package))


def deck_tree(entries: list[dict[str, Any]]) -> tuple[DeckNode, ...]:
    """Turn generator deck entries from an APKG or collection into a tree.

    Args:
        entries: Direct card counts returned by ``inspect_apkg`` or the
            generator's ``collection_decks`` public API.

    Returns:
        Top-level deck nodes with implicit parents and direct card counts.
    """
    counts = _deck_counts(entries)
    _add_missing_parents(counts)
    return _children("", counts)


def save_decks(path: Path, decks: tuple[DeckNode, ...]) -> None:
    """Store one inspected deck tree atomically as JSON.

    Args:
        path: Result destination inside a job folder.
        decks: Tree returned by ``inspect_decks``.

    Returns:
        None.
    """
    _write_json(path, [_node_data(deck) for deck in decks])


def load_decks(path: Path) -> tuple[DeckNode, ...]:
    """Read a previously saved deck tree.

    Args:
        path: Result file created by ``save_decks``.

    Returns:
        Top-level deck nodes in their stored order.

    Raises:
        OSError: If the result file cannot be read.
        ValueError: If its content does not have the expected shape.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Deck-Ergebnis ist keine Liste.")
    return tuple(_node_from_data(item) for item in data)


class DecksRunner:
    """Inspect the APKG upload of a deck job in the serial worker.

    Attributes:
        store: Job storage holding uploads and the resulting deck tree.
    """

    def __init__(self, store: JobStore) -> None:
        """Remember the job storage.

        Args:
            store: Job store containing the uploaded APKG files.
        """
        self.store = store

    def __call__(self, job: Job, report: Reporter, cancel: CancelCheck) -> None:
        """Inspect one APKG and write its deck tree into the job folder.

        Reading an APKG opens a temporary Anki collection and therefore runs
        in the same serial worker as all other APKG work. The generator API
        does not offer a cancellation point for inspection.

        Args:
            job: Queued deck-inspection job with an APKG upload.
            report: Receives user-visible job notices.
            cancel: Cancellation check, unused while APKG inspection runs.

        Returns:
            None.

        Raises:
            FlashcardError: If the APKG cannot be opened or inspected.
        """
        del cancel
        locale = str(job.options.get("locale", "en"))
        report(
            {
                "type": "notice",
                "text": translate_with_fallback(locale, "Reading APKG …", de="APKG wird gelesen …"),
                "level": "info",
            }
        )
        decks = inspect_decks(self.store.upload_path(job))
        save_decks(self.store.job_dir(job.id) / DECKS_FILE, decks)
        report(
            {
                "type": "notice",
                "text": translate_with_fallback(
                    locale,
                    "Found {count} top-level decks.",
                    de="{count} Decks der obersten Ebene gefunden.",
                    count=len(decks),
                ),
                "level": "info",
            }
        )


def _deck_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    """Extract full deck names and direct card counts from the generator result.

    Args:
        entries: Dictionaries returned by ``inspect_apkg``.

    Returns:
        Full deck name to direct card count.
    """
    return {str(entry["name"]): int(entry["cards"]) for entry in entries}


def _add_missing_parents(counts: dict[str, int]) -> None:
    """Add implicit parent decks needed to display a complete tree.

    Args:
        counts: Mutable full deck name to direct card count mapping.

    Returns:
        None. Missing parent names receive a direct count of zero.
    """
    for name in tuple(counts):
        levels = name.split("::")
        for index in range(1, len(levels)):
            counts.setdefault("::".join(levels[:index]), 0)


def _children(parent: str, counts: dict[str, int]) -> tuple[DeckNode, ...]:
    """Build direct children of one deck from a flat count mapping.

    Args:
        parent: Full parent name, or an empty string for the root.
        counts: Full deck name to direct card count mapping.

    Returns:
        Children sorted case-insensitively by their full names.
    """
    prefix = f"{parent}::" if parent else ""
    direct = [
        name for name in counts if name.startswith(prefix) and "::" not in name.removeprefix(prefix)
    ]
    return tuple(
        DeckNode(
            name=name.removeprefix(prefix),
            full_name=name,
            cards=counts[name],
            children=_children(name, counts),
        )
        for name in sorted(direct, key=str.casefold)
    )


def _node_data(node: DeckNode) -> dict[str, Any]:
    """Turn a deck node into JSON-safe data.

    Args:
        node: Tree node to serialize.

    Returns:
        Mapping with the node fields and recursively serialized children.
    """
    return {
        "name": node.name,
        "full_name": node.full_name,
        "cards": node.cards,
        "children": [_node_data(child) for child in node.children],
    }


def _node_from_data(data: Any) -> DeckNode:
    """Restore one deck node from stored JSON data.

    Args:
        data: Candidate mapping loaded from the result file.

    Returns:
        The restored immutable tree node.

    Raises:
        ValueError: If a required field or children list has the wrong type.
    """
    if not isinstance(data, dict) or not isinstance(data.get("children"), list):
        raise ValueError("Ungültiges Deck-Ergebnis.")
    name = data.get("name")
    full_name = data.get("full_name")
    cards = data.get("cards")
    if not isinstance(name, str) or not isinstance(full_name, str) or not isinstance(cards, int):
        raise ValueError("Ungültiges Deck-Ergebnis.")
    children = tuple(_node_from_data(child) for child in data["children"])
    return DeckNode(name, full_name, cards, children)


def _write_json(path: Path, data: Any) -> None:
    """Write JSON beside its destination and replace it atomically.

    Args:
        path: Destination in an existing job folder.
        data: JSON-safe value to store.

    Returns:
        None.
    """
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as temporary:
        json.dump(data, temporary, ensure_ascii=False, indent=2)
    os.replace(temporary.name, path)
