"""Tests for the generation runner with simulated AI calls (AS-001, AS-003)."""

import io
import json
from pathlib import Path
from typing import Any

import pytest
from anki_flashcards import pipeline
from anki_flashcards.apkg import create_apkg
from anki_flashcards.errors import FlashcardError, GenerationCancelled
from anki_flashcards.models import Card

from anki_studio.forms import GenerateForm
from anki_studio.generation import (
    CARDS_FILE,
    TARGET_DIR,
    GenerationRunner,
    job_options,
    transfer_notice,
)
from anki_studio.generator_config import effective_settings, load_generator_config
from anki_studio.jobs import Job, JobStore
from anki_studio.uploads import APKG

GENERATOR_YAML = """
default_profile: lokal
generation:
  language: Englisch
pdf_conversion:
  models_dir: {models}
  pictures:
    profile: vision
models:
  lokal:
    model: ollama/llama3.2
  nativ:
    model: openai/gpt-4o-mini
    pdf_mode: native
  vision:
    model: ollama/llava
    image_input: true
"""

CARDS = [Card(front="Was ist Ohm?", back="Einheit des Widerstands")]


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    """Write the generator YAML used by the tests.

    Args:
        tmp_path: Temporary test folder.

    Returns:
        Absolute path of ``config.yaml``.
    """
    path = tmp_path / "config.yaml"
    path.write_text(GENERATOR_YAML.format(models=tmp_path / "models"), encoding="utf-8")
    return path


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    """Provide an empty job store.

    Args:
        tmp_path: Temporary test folder.

    Returns:
        A store rooted at ``<tmp_path>/jobs``.
    """
    return JobStore(tmp_path / "jobs")


@pytest.fixture
def ai_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace the AI call of the pipeline with a recorder returning cards.

    Args:
        monkeypatch: Pytest fixture for replacing attributes.

    Returns:
        A list receiving the keyword arguments of every call.
    """
    calls: list[dict[str, Any]] = []

    def fake_generate_cards(document: Any, ai: Any, **kwargs: Any) -> list[Card]:
        """Report one chunk and return fixed cards.

        Args:
            document: Extracted document.
            ai: Provider settings.
            **kwargs: Generation options including ``progress``.

        Returns:
            The fixed test cards.
        """
        calls.append({"model": ai.model, "text": document.text, **kwargs})
        kwargs["progress"](1, 1, len(CARDS))
        return list(CARDS)

    monkeypatch.setattr(pipeline, "generate_cards", fake_generate_cards)
    return calls


def new_job(store: JobStore, form: dict[str, str], target_file: str | None = None) -> Job:
    """Create a Markdown job with the given form values.

    Args:
        store: Job store.
        form: Raw form values.
        target_file: Name of an APKG to extend, or None.

    Returns:
        The queued job.
    """
    options = job_options(GenerateForm.model_validate(form), target_file)
    return store.create(io.BytesIO(b"# Ohm\n\nWiderstand."), "skript.md", 19, options)


def run(store: JobStore, config_path: Path, job: Job, cancel: bool = False) -> list[dict]:
    """Run a job directly and collect its events.

    Args:
        store: Job store.
        config_path: Generator YAML.
        job: Job to run.
        cancel: Value returned by the cancellation check.

    Returns:
        The reported events.
    """
    events: list[dict] = []
    GenerationRunner(store, config_path)(job, events.append, lambda: cancel)
    return events


def test_runner_saves_cards_and_reports_events(
    store: JobStore, config_path: Path, ai_calls: list[dict[str, Any]]
) -> None:
    """A Markdown job ends with cards.json and generator events.

    Args:
        store: Job store.
        config_path: Generator YAML.
        ai_calls: Recorded AI calls.
    """
    job = new_job(store, {"deck": "EL1", "limit": "5"})

    events = run(store, config_path, job)

    saved = json.loads((store.job_dir(job.id) / CARDS_FILE).read_text(encoding="utf-8"))
    assert saved["deck"] == "EL1"
    assert saved["cards"] == [card.model_dump(exclude_none=True) for card in CARDS]
    assert ai_calls[0]["model"] == "ollama/llama3.2"
    assert (ai_calls[0]["limit"], ai_calls[0]["language"]) == (5, "Englisch")
    assert "Widerstand" in ai_calls[0]["text"]
    types = [event["type"] for event in events]
    assert types == ["stage_started", "stage_progress", "stage_finished", "cards_saved"]
    json.dumps(events)


def test_native_mode_needs_confirmation(
    store: JobStore, config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without confirmation nothing is uploaded and the job fails.

    Args:
        store: Job store.
        config_path: Generator YAML.
        monkeypatch: Pytest fixture for replacing attributes.
    """
    uploads: list[Path] = []
    monkeypatch.setattr(
        pipeline, "generate_native_cards", lambda path, *args, **kwargs: uploads.append(path)
    )
    job = new_job(store, {"profile": "nativ"})

    with pytest.raises(FlashcardError, match="nicht bestätigt"):
        run(store, config_path, job)

    assert uploads == []


def test_confirmed_native_mode_announces_transfer(
    store: JobStore, config_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With confirmation the upload runs and is announced as ``transfer``.

    Args:
        store: Job store.
        config_path: Generator YAML.
        monkeypatch: Pytest fixture for replacing attributes.
    """
    monkeypatch.setattr(pipeline, "generate_native_cards", lambda *args, **kwargs: list(CARDS))
    job = new_job(store, {"profile": "nativ", "confirm_transfer": "on"})

    events = run(store, config_path, job)

    assert events[0] == {
        "type": "notice",
        "text": "Native PDF mode: uploading the original document to the selected provider.",
        "level": "transfer",
    }


def test_cancelled_job_writes_no_cards(
    store: JobStore, config_path: Path, ai_calls: list[dict[str, Any]]
) -> None:
    """A job cancelled before the start leaves no card file.

    Args:
        store: Job store.
        config_path: Generator YAML.
        ai_calls: Recorded AI calls.
    """
    job = new_job(store, {})

    with pytest.raises(GenerationCancelled):
        run(store, config_path, job, cancel=True)

    assert ai_calls == []
    assert not (store.job_dir(job.id) / CARDS_FILE).exists()


def test_extending_an_apkg_reads_its_subdecks(
    store: JobStore, config_path: Path, ai_calls: list[dict[str, Any]], tmp_path: Path
) -> None:
    """The uploaded package provides the subdeck context and must exist.

    Args:
        store: Job store.
        config_path: Generator YAML.
        ai_calls: Recorded AI calls.
        tmp_path: Temporary test folder.
    """
    package = tmp_path / "el1.apkg"
    create_apkg(package, "EL1", [Card(front="Alt", back="Karte", subdeck="Grundlagen")])
    job = new_job(store, {"deck": "EL1", "subdecks": "true", "target": "extend_apkg"}, "el1.apkg")
    with package.open("rb") as source:
        store.add_file(job.id, TARGET_DIR, source, "el1.apkg", package.stat().st_size, APKG)

    events = run(store, config_path, job)

    context = ai_calls[0]["subdecks"]
    assert [subdeck.name for subdeck in context.existing] == ["Grundlagen"]
    assert events[0]["type"] == "notice"


def test_relative_models_dir_blocks_structured_mode(
    store: JobStore, tmp_path: Path, ai_calls: list[dict[str, Any]]
) -> None:
    """The structured mode needs an absolute models folder in the YAML.

    Args:
        store: Job store.
        tmp_path: Temporary test folder.
        ai_calls: Recorded AI calls.
    """
    config_path = tmp_path / "relative.yaml"
    config_path.write_text("pdf_conversion:\n  models_dir: models\n", encoding="utf-8")
    job = new_job(store, {"pdf_mode": "structured", "model": "ollama/llama3.2"})

    with pytest.raises(FlashcardError, match="models_dir"):
        run(store, config_path, job)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({}, None),
        ({"profile": "nativ"}, "vollständige Dokument"),
        ({"pdf_mode": "structured", "picture_backend": "profile"}, "Bildausschnitte"),
        ({"pdf_mode": "structured", "picture_backend": "local"}, None),
        ({"pdf_mode": "local", "picture_backend": "profile"}, None),
    ],
)
def test_transfer_notice(config_path: Path, values: dict[str, str], expected: str | None) -> None:
    """Only native mode and picture profiles in structured mode transfer content.

    Args:
        config_path: Generator YAML.
        values: Raw form values.
        expected: Expected part of the notice, or None.
    """
    generator = load_generator_config(config_path)
    form = GenerateForm.model_validate(values)

    notice = transfer_notice(effective_settings(generator, form.generator_values()))

    assert notice == expected if expected is None else expected in notice
