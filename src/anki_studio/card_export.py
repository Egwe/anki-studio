"""Export uploaded card JSON to an APKG or synchronized collection (AS-008)."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from anki_flashcards.errors import FlashcardError
from anki_flashcards.models import deduplicate_cards, load_cards
from anki_flashcards.pipeline import run_export
from anki_flashcards.settings import ExportSettings, resolve_export_settings

from anki_studio.generator_config import load_generator_config
from anki_studio.i18n import translate_with_fallback
from anki_studio.jobs import Job, JobStore
from anki_studio.sync import SyncService
from anki_studio.worker import CancelCheck, Reporter

EXPORT_KIND = "export"
EXPORT_FILE = "export.apkg"
EXPORT_RESULT_FILE = "export-result.json"


class ExportRunner:
    """Export one uploaded card JSON file through the generator.

    Attributes:
        store: Job storage containing the card JSON upload and possible APKG.
        config_path: Absolute generator YAML path used to resolve export settings.
        sync: Optional safe collection service required for collection targets.
    """

    def __init__(self, store: JobStore, config_path: Path, sync: SyncService | None = None) -> None:
        """Remember the job storage, configuration, and collection service.

        Args:
            store: Job store containing export inputs and outputs.
            config_path: Absolute generator YAML path.
            sync: Safe collection service; collection targets require it.
        """
        self.store = store
        self.config_path = config_path
        self.sync = sync

    def __call__(self, job: Job, report: Reporter, cancel: CancelCheck) -> None:
        """Validate an uploaded JSON file and export it to its chosen target.

        Args:
            job: Queued export job with deck, target, and JSON upload.
            report: Receives user-visible job notices.
            cancel: Checked by the sync service before a collection mutation.

        Returns:
            None.

        Raises:
            FlashcardError: If configuration, card JSON, deck, target, APKG,
                or safe collection synchronization is invalid.
        """
        locale = str(job.options.get("locale", "en"))
        report(
            {
                "type": "notice",
                "text": translate_with_fallback(
                    locale, "Checking card JSON …", de="Karten-JSON wird geprüft …"
                ),
                "level": "info",
            }
        )
        generator = load_generator_config(self.config_path)
        settings = self._settings(job, generator)
        if job.options.get("target", "new_apkg") == "collection":
            self._write_collection(job, settings, report, cancel)
            return
        self._write_apkg(settings, report, locale)

    def _settings(self, job: Job, generator: Any) -> ExportSettings:
        """Resolve the generator's export settings with an explicit job path.

        Args:
            job: Export job holding the uploaded JSON and target deck option.
            generator: Loaded generator configuration boundary.

        Returns:
            Resolved generator export settings.
        """
        return resolve_export_settings(
            {
                "cards_file": self.store.upload_path(job),
                "output": self.store.job_dir(job.id) / EXPORT_FILE,
                "deck": job.options.get("deck", ""),
                "extend": False,
            },
            generator.config,
            generator.path,
        )

    @staticmethod
    def _write_apkg(settings: ExportSettings, report: Reporter, locale: str) -> None:
        """Write a new APKG through the generator's complete export API.

        Args:
            settings: Resolved card-JSON-to-APKG settings.
            report: Receives the add-count notice.
            locale: Interface language captured for the job.

        Returns:
            None.
        """
        result = run_export(settings)
        report(
            {
                "type": "notice",
                "text": translate_with_fallback(
                    locale,
                    "Wrote {count} cards for deck “{deck}”.",
                    de="{count} Karten für Deck „{deck}“ geschrieben.",
                    count=result.added,
                    deck=result.deck,
                ),
                "level": "info",
            }
        )

    def _write_collection(
        self, job: Job, settings: ExportSettings, report: Reporter, cancel: CancelCheck
    ) -> None:
        """Write validated card JSON through the safe pre/post-sync operation.

        Args:
            job: Running card-JSON export task.
            settings: Resolved card JSON input and target deck.
            report: Receives progress notices.
            cancel: Checked by the sync service before its collection mutation.

        Returns:
            None.

        Raises:
            FlashcardError: If no collection service is configured, the JSON
                is invalid, or safe synchronization refuses the write.
        """
        if self.sync is None:
            raise FlashcardError("Sammlungsziel ist nicht eingerichtet.")
        cards = deduplicate_cards(load_cards(settings.cards_file))
        result, outcome = self.sync.write_cards(
            settings.deck,
            cards,
            report,
            cancel,
            locale=str(job.options.get("locale", "en")),
        )
        _write_json(
            self.store.job_dir(job.id) / EXPORT_RESULT_FILE,
            {
                "target": "collection",
                "deck": result.deck,
                "added": result.added,
                "skipped": result.skipped,
                "added_by_deck": result.added_by_deck,
                "sync_result": outcome.result,
            },
        )
        report(
            {
                "type": "notice",
                "text": (
                    translate_with_fallback(
                        str(job.options.get("locale", "en")),
                        "Wrote {added} cards in deck “{deck}”; {skipped} already present.",
                        de=(
                            "{added} Karten in Deck „{deck}“ geschrieben; "
                            "{skipped} schon vorhanden."
                        ),
                        added=result.added,
                        deck=result.deck,
                        skipped=result.skipped,
                    )
                ),
                "level": "info",
            }
        )


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomically store a non-secret collection export result in its job.

    Args:
        path: Destination below the current export job folder.
        data: JSON-safe add/skip and final sync result.

    Returns:
        None.
    """
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as temporary:
        json.dump(data, temporary, ensure_ascii=False, indent=2)
    os.replace(temporary.name, path)
