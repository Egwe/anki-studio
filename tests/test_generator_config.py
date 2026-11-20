"""Tests for loading the generator configuration and its defaults."""

from pathlib import Path

import pytest
from anki_flashcards.config import PDFMode
from anki_flashcards.errors import FlashcardError

from anki_studio.generator_config import (
    effective_settings,
    load_generator_config,
    profile_views,
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
