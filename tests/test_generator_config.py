"""Tests for loading the generator configuration and its defaults."""

import re
from pathlib import Path

import pytest
from anki_flashcards.config import PDFMode
from anki_flashcards.errors import FlashcardError

from anki_studio.generator_config import (
    TEMPLATE,
    effective_settings,
    ensure_generator_config,
    load_generator_config,
    profile_views,
    template_config,
)

CONFIG = """
default_profile: lokal
generation:
  language: Englisch
  limit: 20
pdf_conversion:
  models_dir: /var/lib/anki-studio/models
models:
  lokal:
    model: ollama/llama3.2
  nativ:
    model: openai/gpt-4o-mini
    api_key_env: TEST_STUDIO_KEY
    pdf_mode: native
"""


def write_config(tmp_path: Path, text: str = CONFIG) -> Path:
    """Write a generator YAML into the test folder.

    Args:
        tmp_path: Temporary test folder.
        text: YAML content.

    Returns:
        Path of the written ``config.yaml``.
    """
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_effective_defaults_come_from_the_generator(tmp_path: Path) -> None:
    """YAML values and the default profile determine the effective settings.

    Args:
        tmp_path: Temporary test folder.
    """
    generator = load_generator_config(write_config(tmp_path))

    settings = effective_settings(generator, {})

    assert generator.path == tmp_path / "config.yaml"
    assert (settings.profile_name, settings.ai.model) == ("lokal", "ollama/llama3.2")
    assert (settings.language, settings.limit, settings.pdf_mode) == ("Englisch", 20, "local")


def test_explicit_values_win(tmp_path: Path) -> None:
    """Form values override YAML and profile.

    Args:
        tmp_path: Temporary test folder.
    """
    generator = load_generator_config(write_config(tmp_path))

    settings = effective_settings(generator, {"profile": "nativ", "limit": 0})

    assert settings.pdf_mode is PDFMode.NATIVE
    assert settings.limit == 0


def test_profile_views_show_mode_and_key_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Profiles list their effective PDF mode and only the key status.

    Args:
        tmp_path: Temporary test folder.
        monkeypatch: Pytest fixture for environment changes.
    """
    monkeypatch.setenv("TEST_STUDIO_KEY", "sk-geheim")
    views = profile_views(load_generator_config(write_config(tmp_path)))

    assert [(view.name, view.pdf_mode, view.key_status) for view in views] == [
        ("lokal", PDFMode.LOCAL, "nicht nötig"),
        ("nativ", PDFMode.NATIVE, "gesetzt"),
    ]
    assert "sk-geheim" not in repr(views)


def test_missing_key_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A profile whose key variable is empty shows ``fehlt``.

    Args:
        tmp_path: Temporary test folder.
        monkeypatch: Pytest fixture for environment changes.
    """
    monkeypatch.delenv("TEST_STUDIO_KEY", raising=False)

    views = profile_views(load_generator_config(write_config(tmp_path)))

    assert views[1].key_status == "fehlt"


def test_missing_config_is_an_error(tmp_path: Path) -> None:
    """An explicit but missing YAML file is reported, never silently replaced.

    Args:
        tmp_path: Temporary test folder.
    """
    with pytest.raises(FlashcardError):
        load_generator_config(tmp_path / "fehlt.yaml")


def test_environment_config_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``ANKI_CONFIG`` never replaces the configured path.

    Args:
        tmp_path: Temporary test folder.
        monkeypatch: Pytest fixture for environment changes.
    """
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.setenv("ANKI_CONFIG", str(write_config(other, "models: {}\n")))

    generator = load_generator_config(write_config(tmp_path))

    assert list(generator.config.models) == ["lokal", "nativ"]


STANDARD_PROFILES = {
    "ollama-local",
    "ollama-vision",
    "openai-default",
    "openai-native-pdf",
    "anthropic-default",
    "gemini-default",
    "mistral-default",
    "deepseek-default",
    "openrouter-default",
    "groq-default",
    "xai-default",
    "moonshot-default",
    "custom-openai-compatible",
}


def test_template_lists_every_provider(tmp_path: Path) -> None:
    """The bundled template is valid and has a profile per provider (AS-015).

    Args:
        tmp_path: Temporary test folder.
    """
    config = template_config(tmp_path / "models")

    assert set(config.models) == STANDARD_PROFILES
    assert config.pdf_conversion.models_dir == tmp_path / "models"
    assert config.models["openai-native-pdf"].pdf_mode is PDFMode.NATIVE
    assert "max_output_tokens" in config.models["openai-native-pdf"].options
    assert config.models["ollama-vision"].image_input


def test_template_contains_no_private_addresses() -> None:
    """The public repository template names no home-network addresses."""
    text = TEMPLATE.read_text(encoding="utf-8")

    assert not re.search(r"\b(10|192\.168|172\.(1[6-9]|2\d|3[01]))\.\d+\.\d+", text)


def test_missing_config_is_created_with_comments(tmp_path: Path) -> None:
    """Without a file the template is written, readable only by the owner.

    Args:
        tmp_path: Temporary test folder.
    """
    path = tmp_path / "data" / "generator.yaml"

    added = ensure_generator_config(path, tmp_path / "models")

    assert set(added) == STANDARD_PROFILES
    assert "api_key_env nennt nur die Umgebungsvariable" in path.read_text(encoding="utf-8")
    assert path.stat().st_mode & 0o777 == 0o600
    assert load_generator_config(path).config.pdf_conversion.models_dir == tmp_path / "models"


def test_missing_profiles_are_added_without_changing_others(tmp_path: Path) -> None:
    """Existing profiles and values stay; only absent standard profiles appear.

    Args:
        tmp_path: Temporary test folder.
    """
    path = write_config(tmp_path)

    added = ensure_generator_config(path, tmp_path / "models")

    config = load_generator_config(path).config
    assert "nativ" not in added and "lokal" not in added
    assert set(added) == STANDARD_PROFILES
    assert config.models["lokal"].model == "ollama/llama3.2"
    assert config.generation.language == "Englisch"
    assert config.default_profile == "lokal"
    assert ensure_generator_config(path, tmp_path / "models") == []


def test_complete_config_is_left_untouched(tmp_path: Path) -> None:
    """A file with every standard profile is not rewritten.

    Args:
        tmp_path: Temporary test folder.
    """
    path = tmp_path / "generator.yaml"
    ensure_generator_config(path, tmp_path / "models")
    before = path.read_text(encoding="utf-8")

    assert ensure_generator_config(path, tmp_path / "models") == []
    assert path.read_text(encoding="utf-8") == before
