"""Tests for the state of the structured mode and the model download (AS-010, AS-041)."""

import io
from pathlib import Path
from typing import Any

import pytest
from anki_flashcards.config import AppConfig
from anki_flashcards.errors import FlashcardError
from anki_flashcards.model_storage import ModelStorage, record_components
from anki_flashcards.pipeline import Notice
from fastapi.testclient import TestClient

from anki_studio import models_task
from anki_studio.generation import KindRunner
from anki_studio.jobs import Job, JobStatus
from anki_studio.models_task import structured_state
from anki_studio.settings import StudioSettings
from tests.conftest import wait_until


def config_with_models(models_dir: Path, **conversion: Any) -> AppConfig:
    """Build a generator configuration with the given models folder.

    Args:
        models_dir: Absolute models folder.
        **conversion: Further ``pdf_conversion`` values.

    Returns:
        The validated configuration.
    """
    return AppConfig.model_validate(
        {"pdf_conversion": {"models_dir": str(models_dir), **conversion}}
    )


def test_state_lists_required_and_downloaded_components(tmp_path: Path) -> None:
    """Required components follow the configuration; the manifest marks present ones.

    Args:
        tmp_path: Temporary test folder.
    """
    record_components(ModelStorage(root=tmp_path), {"layout", "rapidocr"})

    state = structured_state(config_with_models(tmp_path))
    without = structured_state(
        config_with_models(tmp_path, formulas=False, pictures={"backend": "none"})
    )

    names = {component.name: component.downloaded for component in state.components}
    assert names["layout"] and names["rapidocr"]
    assert not names["code_formula"]
    assert "picture:HuggingFaceTB/SmolVLM-256M-Instruct" in names
    assert {component.name for component in without.components} == {
        "layout",
        "picture_classifier",
        "rapidocr",
        "tableformer",
    }


def test_state_without_docling_skips_gpu_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without Docling no GPU check runs (and torch is never imported).

    Args:
        tmp_path: Temporary test folder.
        monkeypatch: Pytest fixture for replacing attributes.
    """
    monkeypatch.setattr(models_task.importlib.util, "find_spec", lambda name: None)
    monkeypatch.setattr(models_task, "_gpu", lambda: pytest.fail("GPU-Prüfung ohne Docling"))

    state = structured_state(config_with_models(tmp_path))

    assert (state.docling, state.device, state.gpu_problem) == (False, None, None)


@pytest.mark.parametrize(
    ("gpu", "expected"),
    [
        (("cuda", None), "nutzbar"),
        ((None, "PyTorch 2.99 has no kernels for sm_50"), "no kernels for sm_50"),
    ],
)
def test_page_shows_gpu_state(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch, gpu: tuple[Any, Any], expected: str
) -> None:
    """The page names a usable GPU or explains why it cannot be used.

    Args:
        auth_client: Logged-in test client.
        monkeypatch: Pytest fixture for replacing attributes.
        gpu: Simulated result of the GPU check.
        expected: Expected text on the page.
    """
    monkeypatch.setattr(models_task.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(models_task, "_gpu", lambda: gpu)

    page = auth_client.get("/settings/models").text

    assert expected in page
    assert "Fehlende Modelle herunterladen</button>" in page


def test_page_without_docling_disables_download(
    auth_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without Docling the page says so and the download is disabled.

    Args:
        auth_client: Logged-in test client.
        monkeypatch: Pytest fixture for replacing attributes.
    """
    monkeypatch.setattr(models_task.importlib.util, "find_spec", lambda name: None)

    page = auth_client.get("/settings/models").text

    assert "nicht installiert" in page
    assert '<button type="submit" disabled>' in page


def test_download_runs_as_job(
    auth_client: TestClient, studio_settings: StudioSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The download is a job whose notices reach the job page.

    Args:
        auth_client: Logged-in test client.
        studio_settings: Settings of the test application.
        monkeypatch: Pytest fixture for replacing attributes.
    """
    calls: list[Path] = []

    def fake_prepare(config: AppConfig, config_path: Path, *, report: Any, **kwargs: Any) -> Path:
        """Announce one download instead of loading models.

        Args:
            config: Generator configuration.
            config_path: Generator YAML.
            report: Generator event callback.
            **kwargs: Further options.

        Returns:
            The models folder.
        """
        calls.append(config_path)
        report(Notice("Lade Docling-Modelle ..."))
        return config.pdf_conversion.models_dir

    monkeypatch.setattr(models_task, "prepare_models", fake_prepare)

    response = auth_client.post("/settings/models/download", follow_redirects=False)

    job_id = response.headers["location"].rsplit("/", 1)[-1]
    store = auth_client.app.state.jobs
    wait_until(lambda: store.get(job_id).status is JobStatus.DONE)
    page = auth_client.get(f"/jobs/{job_id}").text
    assert "Modelle herunterladen" in page
    assert "Lade Docling-Modelle" in page and "Modelle bereit" in page
    assert "<strong>Optionen</strong>" not in page
    assert calls == [studio_settings.generator_path]


def test_kind_runner_dispatches_and_refuses_unknown_kinds() -> None:
    """Jobs go to the runner of their kind; old jobs without kind generate."""
    seen: list[str] = []
    runner = KindRunner({"generate": lambda job, report, cancel: seen.append("generate")})
    job = Job.model_validate(
        {
            "id": "0" * 32,
            "created_at": "2026-11-21T00:00:00Z",
            "updated_at": "2026-11-21T00:00:00Z",
            "source_name": "x",
        }
    )

    runner(job, lambda event: None, lambda: False)
    with pytest.raises(FlashcardError, match="Unbekannte Job-Art"):
        runner(
            job.model_copy(update={"options": {"kind": "magie"}}), lambda event: None, lambda: False
        )

    assert seen == ["generate"]


def test_task_jobs_have_no_upload(tmp_path: Path) -> None:
    """Task jobs are created without upload folder and listed by title.

    Args:
        tmp_path: Temporary test folder.
    """
    from anki_studio.jobs import JobStore

    store = JobStore(tmp_path / "jobs")
    task = store.create_task("Modelle herunterladen", {"kind": "models"})
    store.create(io.BytesIO(b"# T"), "skript.md", 3)

    assert not (store.job_dir(task.id) / "upload").exists()
    assert "Modelle herunterladen" in [job.source_name for job in store.list_jobs()]
