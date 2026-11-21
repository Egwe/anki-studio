"""Show the state of the structured PDF mode and download its models (AS-010, AS-041).

The download runs as a job in the worker; its notices reach the job page
live like generation events. Displaying the state has no side effects:
the models folder is only read.
"""

import importlib.util
from dataclasses import dataclass
from pathlib import Path

from anki_flashcards.config import AppConfig, PictureBackend
from anki_flashcards.docling_pdf import BASE_COMPONENTS, FORMULA_COMPONENT
from anki_flashcards.model_storage import ModelStorage, downloaded_components
from anki_flashcards.pipeline import event_to_dict, prepare_models

from anki_studio.generator_config import load_generator_config
from anki_studio.jobs import Job
from anki_studio.worker import CancelCheck, Reporter

MODELS_KIND = "models"
MODELS_TITLE = "Modelle herunterladen"


@dataclass(frozen=True)
class ComponentState:
    """Describe one model component of the structured mode.

    Attributes:
        name: Component name of the generator's manifest.
        downloaded: Whether it was downloaded completely.
    """

    name: str
    downloaded: bool


@dataclass(frozen=True)
class StructuredState:
    """Describe whether the structured PDF mode can run.

    Attributes:
        docling: Whether the ``pdf`` extra with Docling is installed.
        device: Usable accelerator (``cuda``, ``xpu``, ``mps``) or None.
        gpu_problem: Explanation of a GPU the PyTorch build cannot use.
        models_dir: Models folder of the configuration.
        components: Required components and whether they are present.
    """

    docling: bool
    device: str | None
    gpu_problem: str | None
    models_dir: Path
    components: list[ComponentState]


def structured_state(config: AppConfig) -> StructuredState:
    """Collect the state of Docling, the GPU, and the model components.

    Args:
        config: Generator configuration; decides the models folder and
            whether the formula and local picture models are needed.

    Returns:
        The state; without Docling no GPU check is made.
    """
    conversion = config.pdf_conversion
    storage = ModelStorage(root=conversion.models_dir)
    present = downloaded_components(storage)
    required = sorted(BASE_COMPONENTS | ({FORMULA_COMPONENT} if conversion.formulas else set()))
    if conversion.pictures.backend == PictureBackend.LOCAL:
        required.append(f"picture:{conversion.pictures.model}")
    components = [ComponentState(name, name in present) for name in required]
    docling = importlib.util.find_spec("docling") is not None
    device, problem = _gpu() if docling else (None, None)
    return StructuredState(docling, device, problem, storage.root, components)


def _gpu() -> tuple[str | None, str | None]:
    """Ask the generator which accelerator PyTorch can use.

    Returns:
        The device name or None, and the reason a present CUDA GPU is not
        usable, or None.
    """
    from anki_flashcards.docling_pdf import available_accelerator, cuda_architecture_problem

    device = available_accelerator()
    if device is not None:
        return device, None
    import torch

    if not torch.cuda.is_available():
        return None, None
    return None, cuda_architecture_problem(torch)


class ModelsRunner:
    """Download the structured mode's models in the worker.

    Attributes:
        config_path: Generator YAML.
    """

    def __init__(self, config_path: Path) -> None:
        """Remember the generator YAML.

        Args:
            config_path: Generator YAML.
        """
        self.config_path = config_path

    def __call__(self, job: Job, report: Reporter, cancel: CancelCheck) -> None:
        """Download missing models into the configured folder.

        The generator announces every download as a notice; a running
        download cannot be cancelled, only a waiting job.

        Args:
            job: The running job.
            report: Receives JSON-safe events.
            cancel: Cancellation check (not used during downloads).

        Returns:
            None.

        Raises:
            FlashcardError: If Docling is missing or a download fails.
        """
        generator = load_generator_config(self.config_path)
        folder = prepare_models(
            generator.config, generator.path, report=lambda event: report(event_to_dict(event))
        )
        report({"type": "notice", "text": f"Modelle bereit in {folder}.", "level": "info"})
