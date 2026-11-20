"""Tests for loading ``studio.yaml``."""

from pathlib import Path

import pytest

from anki_studio.settings import (
    CONFIG_ENV,
    SettingsError,
    StudioSettings,
    load_settings,
    settings_path,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "studio.example.yaml"


def write(tmp_path: Path, text: str) -> Path:
    """Write a settings file into the test folder.

    Args:
        tmp_path: Temporary test folder.
        text: YAML content.

    Returns:
        Path of the written ``studio.yaml``.
    """
    path = tmp_path / "studio.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_without_file() -> None:
    """Without a settings file the built-in defaults apply."""
    assert load_settings(None) == StudioSettings(host="127.0.0.1", port=8000)


def test_reads_values(tmp_path: Path) -> None:
    """Values from the file replace the defaults."""
    settings = load_settings(write(tmp_path, "host: 0.0.0.0\nport: 8123\n"))

    assert (settings.host, settings.port) == ("0.0.0.0", 8123)


def test_empty_file_uses_defaults(tmp_path: Path) -> None:
    """An empty file is valid and keeps all defaults."""
    assert load_settings(write(tmp_path, "")) == StudioSettings()


def test_example_file_is_valid() -> None:
    """The committed example loads without errors."""
    assert load_settings(EXAMPLE).port == 8000


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    """A misspelled key is reported instead of silently ignored."""
    with pytest.raises(SettingsError, match="prot"):
        load_settings(write(tmp_path, "prot: 8000\n"))


@pytest.mark.parametrize("port", [0, 65536, "abc"])
def test_invalid_port_is_rejected(tmp_path: Path, port: object) -> None:
    """Ports outside 1–65535 or non-numbers are rejected.

    Args:
        tmp_path: Temporary test folder.
        port: Invalid port value.
    """
    with pytest.raises(SettingsError, match="port"):
        load_settings(write(tmp_path, f"port: {port}\n"))


def test_missing_file_is_an_error(tmp_path: Path) -> None:
    """An explicitly selected file must exist."""
    with pytest.raises(SettingsError, match="nicht lesbar"):
        load_settings(tmp_path / "missing.yaml")


def test_invalid_yaml_is_an_error(tmp_path: Path) -> None:
    """Broken YAML syntax is reported with the file name."""
    with pytest.raises(SettingsError, match="kein gültiges YAML"):
        load_settings(write(tmp_path, "port: [8000\n"))


def test_non_mapping_is_an_error(tmp_path: Path) -> None:
    """A YAML list or scalar is no settings file."""
    with pytest.raises(SettingsError, match="Schlüssel und Werte"):
        load_settings(write(tmp_path, "- 8000\n"))


def test_settings_path_prefers_explicit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An explicit path wins over the environment variable.

    Args:
        monkeypatch: Pytest fixture for environment changes.
        tmp_path: Temporary test folder.
    """
    monkeypatch.setenv(CONFIG_ENV, "/etc/anki-studio/studio.yaml")

    assert settings_path(tmp_path / "studio.yaml") == tmp_path / "studio.yaml"


def test_settings_path_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without an explicit path the environment variable is used.

    Args:
        monkeypatch: Pytest fixture for environment changes.
    """
    monkeypatch.setenv(CONFIG_ENV, "/etc/anki-studio/studio.yaml")

    assert settings_path(None) == Path("/etc/anki-studio/studio.yaml")


def test_settings_path_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without explicit path and environment variable the defaults apply.

    Args:
        monkeypatch: Pytest fixture for environment changes.
    """
    monkeypatch.delenv(CONFIG_ENV, raising=False)

    assert settings_path(None) is None
