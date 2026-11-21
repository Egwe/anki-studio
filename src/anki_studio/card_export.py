"""Export uploaded generator card JSON to a new APKG in the job worker (AS-008)."""

from pathlib import Path

from anki_flashcards.pipeline import run_export
from anki_flashcards.settings import resolve_export_settings

from anki_studio.generator_config import load_generator_config
from anki_studio.jobs import Job, JobStore
from anki_studio.worker import CancelCheck, Reporter

EXPORT_KIND = "export"
EXPORT_FILE = "export.apkg"


class ExportRunner:
    """Export one uploaded card JSON file through the generator.

    Attributes:
        store: Job storage containing the card JSON upload and output APKG.
        config_path: Absolute generator YAML path used to resolve export settings.
    """

    def __init__(self, store: JobStore, config_path: Path) -> None:
        """Remember the job storage and generator configuration path.

        Args:
            store: Job store containing export inputs and outputs.
            config_path: Absolute generator YAML path.
        """
        self.store = store
        self.config_path = config_path

    def __call__(self, job: Job, report: Reporter, cancel: CancelCheck) -> None:
        """Write the uploaded card JSON to a new APKG.

        The generator loads and validates the versioned JSON, deduplicates
        cards, validates the output path, and creates the APKG. It has no
        cancellation callback for this operation.

        Args:
            job: Queued export job with ``options.deck`` and a JSON upload.
            report: Receives user-visible job notices.
            cancel: Cancellation check, unused while exporting.

        Returns:
            None.

        Raises:
            FlashcardError: If the configuration, card JSON, deck, or APKG
                output is invalid.
        """
        del cancel
        report({"type": "notice", "text": "Karten-JSON wird exportiert …", "level": "info"})
        generator = load_generator_config(self.config_path)
        output = self.store.job_dir(job.id) / EXPORT_FILE
        settings = resolve_export_settings(
            {
                "cards_file": self.store.upload_path(job),
                "output": output,
                "deck": job.options.get("deck", ""),
                "extend": False,
            },
            generator.config,
            generator.path,
        )
        result = run_export(settings)
        report(
            {
                "type": "notice",
                "text": f"{result.added} Karten für Deck „{result.deck}“ geschrieben.",
                "level": "info",
            }
        )
