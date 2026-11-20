"""Load the generator's YAML configuration and show its effective defaults.

Anki Studio never re-implements the generator's precedence rules
(built-in default → YAML → profile → explicit value). Effective values for
the form are computed by ``anki_flashcards.settings.resolve_generate_settings``
with placeholder paths.
"""

import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from anki_flashcards.config import AppConfig, PDFMode, save_config
from anki_flashcards.errors import FlashcardError
from anki_flashcards.settings import (
    GenerateSettings,
    load_selected_config,
    resolve_generate_settings,
)

PLACEHOLDER_INPUT = Path("/anki-studio/dokument.pdf")
PLACEHOLDER_OUTPUT = Path("/anki-studio/ausgabe.apkg")
TEMPLATE = Path(__file__).parent / "resources" / "generator-template.yaml"
MODELS_DIR_PLACEHOLDER = "__MODELS_DIR__"


@dataclass(frozen=True)
class GeneratorConfig:
    """Hold a loaded generator configuration and its location.

    Attributes:
        config: Validated configuration.
        path: Absolute YAML path; relative YAML paths are resolved next to it.
    """

    config: AppConfig
    path: Path


@dataclass(frozen=True)
class ProfileView:
    """Describe a model profile for the form, without secret values.

    Attributes:
        name: Profile name from ``models``.
        model: Provider and model, for example ``openai/gpt-4o-mini``.
        pdf_mode: Effective PDF mode when this profile is selected.
        image_input: Whether the profile may describe pictures.
        key_status: ``gesetzt``, ``fehlt``, or ``nicht nötig``.
    """

    name: str
    model: str
    pdf_mode: PDFMode
    image_input: bool
    key_status: str


def load_generator_config(path: Path) -> GeneratorConfig:
    """Load the generator YAML from an explicit path.

    The path is always passed explicitly, so neither ``ANKI_CONFIG`` nor a
    ``config.yaml`` in the working directory is consulted.

    Args:
        path: Absolute path of the generator YAML.

    Returns:
        The validated configuration and its absolute path.

    Raises:
        FlashcardError: If the file is missing, unreadable, or invalid.
    """
    config, config_path = load_selected_config(path)
    return GeneratorConfig(config, config_path or path)


def template_text(models_dir: Path) -> str:
    """Return the bundled generator YAML with an absolute models folder.

    Args:
        models_dir: Absolute folder for Docling and picture models.

    Returns:
        The template text including its comments.
    """
    return TEMPLATE.read_text(encoding="utf-8").replace(MODELS_DIR_PLACEHOLDER, str(models_dir))


def template_config(models_dir: Path) -> AppConfig:
    """Parse the bundled template with the generator's schema.

    Args:
        models_dir: Absolute folder for Docling and picture models.

    Returns:
        The validated template configuration with every standard profile.
    """
    return AppConfig.model_validate(yaml.safe_load(template_text(models_dir)))


def ensure_generator_config(path: Path, models_dir: Path) -> list[str]:
    """Create the generator YAML or add the standard profiles it lacks (AS-015).

    A missing file is written from the template, comments included. An
    existing file only gets the missing standard profiles; existing
    profiles and all other values stay as they are. Saving goes through
    the generator's atomic ``save_config`` (comments of that file are lost).

    Args:
        path: Generator YAML inside the data folder.
        models_dir: Absolute models folder for a newly created file.

    Returns:
        Names of the profiles that were added; empty if nothing changed.

    Raises:
        FlashcardError: If an existing file is invalid or cannot be saved.
        OSError: If a new file cannot be written.
    """
    standard = template_config(models_dir).models
    if not path.exists():
        _write_private(path, template_text(models_dir))
        return list(standard)
    config = load_generator_config(path).config
    missing = {name: profile for name, profile in standard.items() if name not in config.models}
    if missing:
        save_config(path, config.model_copy(update={"models": config.models | missing}))
    return list(missing)


def _write_private(path: Path, text: str) -> None:
    """Write a new file readable only by its owner, atomically.

    Args:
        path: Destination; parent folders are created.
        text: File content.

    Returns:
        None.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as temporary:
        temporary.write(text)
    os.replace(temporary.name, path)


def effective_settings(generator: GeneratorConfig, values: Mapping[str, Any]) -> GenerateSettings:
    """Resolve settings for explicit values with placeholder file paths.

    Args:
        generator: Loaded generator configuration.
        values: Explicit form values in the format of
            ``resolve_generate_settings`` (only set keys, enums as enums).

    Returns:
        The settings the generator would use; paths are placeholders.

    Raises:
        FlashcardError: If a profile is unknown or a picture profile is
            missing or not allowed to read images.
    """
    explicit = {"input_file": PLACEHOLDER_INPUT, "output": PLACEHOLDER_OUTPUT, **values}
    return resolve_generate_settings(explicit, generator.config, generator.path)


def profile_views(generator: GeneratorConfig) -> list[ProfileView]:
    """Describe every profile of the configuration for the form.

    Args:
        generator: Loaded generator configuration.

    Returns:
        One entry per profile in configuration order. A profile that cannot
        be resolved is shown with its own PDF mode.
    """
    return [_profile_view(generator, name) for name in generator.config.models]


def _profile_view(generator: GeneratorConfig, name: str) -> ProfileView:
    """Describe one profile with its effective PDF mode and key status.

    Args:
        generator: Loaded generator configuration.
        name: Profile name.

    Returns:
        The profile description.
    """
    profile = generator.config.models[name]
    try:
        settings = effective_settings(generator, {"profile": name})
    except FlashcardError:
        return ProfileView(name, profile.model, profile.pdf_mode, profile.image_input, "fehlt")
    return ProfileView(
        name=name,
        model=profile.model,
        pdf_mode=settings.pdf_mode,
        image_input=profile.image_input,
        key_status=_key_status(profile.api_key_env, settings.ai.api_key),
    )


def _key_status(variable: str | None, value: str | None) -> str:
    """Summarize whether a profile's API key is available.

    Args:
        variable: Name of the environment variable, or None.
        value: Resolved key, or None.

    Returns:
        ``nicht nötig`` without variable, otherwise ``gesetzt`` or ``fehlt``.
    """
    if variable is None:
        return "nicht nötig"
    return "gesetzt" if value else "fehlt"
