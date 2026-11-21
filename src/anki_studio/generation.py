"""Generate the cards of one job with the generator's pipeline (AS-001, AS-003).

The runner only produces cards and saves them as ``cards.json`` in the job
folder; writing a package follows after the review (AS-005). Paths are
always passed explicitly, so ``input_dir``, ``output_dir``,
``source_text_dir`` and ``generation.json_output`` of the YAML are not used.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from anki_flashcards.config import PDFMode, PictureBackend
from anki_flashcards.errors import FlashcardError
from anki_flashcards.models import save_cards
from anki_flashcards.pipeline import (
    PipelineEvent,
    Reporter,
    apkg_subdeck_context,
    event_to_dict,
    produce_cards,
    validate_output,
)
from anki_flashcards.settings import GenerateSettings, resolve_generate_settings

from anki_studio.forms import GenerateForm
from anki_studio.generator_config import GeneratorConfig, load_generator_config
from anki_studio.jobs import Job, JobStore
from anki_studio.worker import CancelCheck
from anki_studio.worker import Reporter as JobReporter

GENERATE_KIND = "generate"
CARDS_FILE = "cards.json"
SOURCE_TEXT_FILE = "source.md"
TARGET_DIR = "target"
NEW_APKG_FILE = "karten.apkg"


@dataclass(frozen=True)
class JobPaths:
    """Hold the explicit file paths of one job.

    Attributes:
        input_file: Uploaded document.
        output: APKG to create, or the uploaded APKG to extend.
        extend: Whether ``output`` is extended.
        source_text: Markdown of a structured conversion.
        cards: Card JSON written after generation.
    """

    input_file: Path
    output: Path
    extend: bool
    source_text: Path
    cards: Path


def job_options(form: GenerateForm, target_file: str | None = None) -> dict[str, Any]:
    """Build the JSON-safe options stored in ``job.json``.

    Args:
        form: Validated generation form.
        target_file: Name of the uploaded APKG to extend, or None.

    Returns:
        ``{"kind": "generate", "form": ..., "target_file": ...}``.
    """
    return {"kind": GENERATE_KIND, "form": form.model_dump(mode="json"), "target_file": target_file}


def job_paths(store: JobStore, job: Job) -> JobPaths:
    """Derive all paths of a job from its folder and options.

    Args:
        store: Job store.
        job: Job whose options were built by ``job_options``.

    Returns:
        The explicit paths for the generator.
    """
    folder = store.job_dir(job.id)
    target_file = job.options.get("target_file")
    extend = target_file is not None
    output = folder / TARGET_DIR / target_file if extend else folder / NEW_APKG_FILE
    return JobPaths(
        input_file=store.upload_path(job),
        output=output,
        extend=extend,
        source_text=folder / SOURCE_TEXT_FILE,
        cards=folder / CARDS_FILE,
    )


def resolve_job_settings(
    generator: GeneratorConfig, form: GenerateForm, paths: JobPaths
) -> GenerateSettings:
    """Resolve the generator settings of a job.

    Args:
        generator: Loaded generator configuration.
        form: Validated generation form.
        paths: Explicit paths of the job.

    Returns:
        The effective settings.

    Raises:
        FlashcardError: If a profile is unknown or a picture profile is
            missing or not allowed to read images.
    """
    values = form.generator_values() | {
        "input_file": paths.input_file,
        "output": paths.output,
        "extend": paths.extend,
        "source_text": paths.source_text,
    }
    return resolve_generate_settings(values, generator.config, generator.path)


def transfer_notice(settings: GenerateSettings) -> str | None:
    """Describe a transfer of document content to a provider, if any.

    Args:
        settings: Effective generator settings.

    Returns:
        A German sentence for ``native`` mode and for the picture backend
        ``profile`` in structured mode, otherwise None.
    """
    if settings.pdf_mode is PDFMode.NATIVE:
        return f"Das vollständige Dokument wird zu {settings.ai.model} hochgeladen."
    conversion = settings.conversion
    if settings.pdf_mode is PDFMode.STRUCTURED and conversion.picture_backend is (
        PictureBackend.PROFILE
    ):
        return f"Bildausschnitte gehen an das Profil „{conversion.picture_profile}“."
    return None


def check_job_settings(
    generator: GeneratorConfig, settings: GenerateSettings, confirmed: bool
) -> None:
    """Refuse a job that transfers content without confirmation.

    Also refuses the structured mode while ``pdf_conversion.models_dir`` is
    relative, because it would resolve to the configuration folder.

    Args:
        generator: Loaded generator configuration.
        settings: Effective generator settings.
        confirmed: Whether the user confirmed the transfer.

    Returns:
        None if the job may start.

    Raises:
        FlashcardError: With a German message for the user.
    """
    notice = transfer_notice(settings)
    if notice is not None and not confirmed:
        raise FlashcardError(f"Datenübertragung nicht bestätigt: {notice}")
    models_dir = generator.config.pdf_conversion.models_dir
    if settings.pdf_mode is PDFMode.STRUCTURED and not models_dir.is_absolute():
        raise FlashcardError(
            "Für den strukturierten PDF-Modus muss pdf_conversion.models_dir in der "
            "Generator-Konfiguration ein absoluter Pfad sein, etwa /var/lib/anki-studio/models."
        )


class GenerationRunner:
    """Run one generation job; used as runner of the ``JobWorker``.

    Attributes:
        store: Job store with the job folders.
        config_path: Absolute path of the generator YAML.
    """

    def __init__(self, store: JobStore, config_path: Path) -> None:
        """Remember where jobs and the generator configuration live.

        Args:
            store: Job store with the job folders.
            config_path: Absolute path of the generator YAML.
        """
        self.store = store
        self.config_path = config_path

    def __call__(self, job: Job, report: JobReporter, cancel: CancelCheck) -> None:
        """Generate the cards of a job and save them as ``cards.json``.

        The YAML is read again for every job, so changes apply without a
        restart. Generator events are passed on as JSON events.

        Args:
            job: The running job.
            report: Receives JSON-safe events for the event log.
            cancel: Returns True when the user cancelled the job.

        Returns:
            None.

        Raises:
            GenerationCancelled: If the job was cancelled.
            FlashcardError: If the configuration, the transfer check, the
                output check, the conversion, or the provider fails.
        """
        form = GenerateForm.model_validate(job.options["form"])
        generator = load_generator_config(self.config_path)
        paths = job_paths(self.store, job)
        settings = resolve_job_settings(generator, form, paths)
        check_job_settings(generator, settings, form.confirm_transfer)
        validate_output(settings.output, settings.extend)
        reporter = _event_reporter(report)
        context = apkg_subdeck_context(settings, report=reporter)
        run = produce_cards(settings, context, report=reporter, cancel=cancel)
        save_cards(paths.cards, run.cards, deck=settings.deck, source=job.source_name)
        report({"type": "cards_saved", "count": len(run.cards), "deck": settings.deck})


class KindRunner:
    """Pick the runner of a job by its ``kind`` option.

    Jobs without ``kind`` are generation jobs (created before kinds existed).

    Attributes:
        runners: Kind name to runner.
    """

    def __init__(self, runners: dict[str, Callable[[Job, JobReporter, CancelCheck], None]]) -> None:
        """Remember the runners.

        Args:
            runners: Kind name to runner.
        """
        self.runners = runners

    def __call__(self, job: Job, report: JobReporter, cancel: CancelCheck) -> None:
        """Run a job with the runner of its kind.

        Args:
            job: The running job.
            report: Receives JSON-safe events.
            cancel: Cancellation check.

        Returns:
            None.

        Raises:
            FlashcardError: If the kind is unknown or the runner fails.
        """
        kind = job.options.get("kind", GENERATE_KIND)
        runner = self.runners.get(kind)
        if runner is None:
            raise FlashcardError(f"Unbekannte Job-Art: {kind}")
        runner(job, report, cancel)


def _event_reporter(report: JobReporter) -> Reporter:
    """Adapt the job reporter to generator events.

    Args:
        report: Receives JSON-safe dictionaries.

    Returns:
        A generator reporter that converts every event with ``event_to_dict``.
    """

    def forward(event: PipelineEvent) -> None:
        """Convert and forward one generator event.

        Args:
            event: Event of the generator pipeline.

        Returns:
            None.
        """
        report(event_to_dict(event))

    return forward
