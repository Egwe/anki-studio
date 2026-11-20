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


def test_defaults_without_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Without a settings file the built-in defaults apply.

    Args:
        monkeypatch: Pytest fixture to change the working directory.
        tmp_path: Temporary working directory.
    """
    monkeypatch.chdir(tmp_path)

    settings = load_settings(None)

    assert (settings.host, settings.port, settings.job_retention_days) == ("127.0.0.1", 8000, 14)
    assert settings.data_dir == tmp_path / "data"


def test_reads_values(tmp_path: Path) -> None:
    """Values from the file replace the defaults."""
    settings = load_settings(write(tmp_path, "host: 0.0.0.0\nport: 8123\n"))

    assert (settings.host, settings.port) == ("0.0.0.0", 8123)


def test_empty_file_uses_defaults(tmp_path: Path) -> None:
    """An empty file is valid and keeps all defaults.

    Args:
        tmp_path: Temporary test folder.
    """
    settings = load_settings(write(tmp_path, ""))

    assert settings == StudioSettings(
        data_dir=tmp_path / "data", generator_config=tmp_path / "config.yaml"
    )


def test_relative_generator_config_is_resolved_next_to_file(tmp_path: Path) -> None:
    """The generator YAML is found next to ``studio.yaml`` unless absolute.

    Args:
        tmp_path: Temporary test folder.
    """
    relative = load_settings(write(tmp_path, "generator_config: generator.yaml\n"))
    absolute = load_settings(write(tmp_path, "generator_config: /etc/anki-studio/config.yaml\n"))

    assert relative.generator_config == tmp_path / "generator.yaml"
    assert absolute.generator_config == Path("/etc/anki-studio/config.yaml")


def test_relative_data_dir_is_resolved_next_to_file(tmp_path: Path) -> None:
    """A relative data folder belongs to the folder of ``studio.yaml``.

    Args:
        tmp_path: Temporary test folder.
    """
    settings = load_settings(write(tmp_path, "data_dir: daten/studio\n"))

    assert settings.data_dir == tmp_path / "daten" / "studio"


def test_absolute_data_dir_is_kept(tmp_path: Path) -> None:
    """An absolute data folder is used as it is.

    Args:
        tmp_path: Temporary test folder.
    """
    settings = load_settings(write(tmp_path, "data_dir: /var/lib/anki-studio\n"))

    assert settings.data_dir == Path("/var/lib/anki-studio")


@pytest.mark.parametrize("days", [0, 3651])
def test_invalid_retention_is_rejected(tmp_path: Path, days: int) -> None:
    """The retention period must be between 1 and 3650 days.

    Args:
        tmp_path: Temporary test folder.
        days: Invalid number of days.
    """
    with pytest.raises(SettingsError, match="job_retention_days"):
        load_settings(write(tmp_path, f"job_retention_days: {days}\n"))


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


def test_allowed_hosts_are_normalized(tmp_path: Path) -> None:
    """Host names are trimmed and lower-cased; IPv6 addresses are allowed.

    Args:
        tmp_path: Temporary test folder.
    """
    settings = load_settings(write(tmp_path, "allowed_hosts: [' Anki-Studio.LAN ', '::1']\n"))

    assert settings.allowed_hosts == ("anki-studio.lan", "::1")


@pytest.mark.parametrize(
    "entry", ["'*'", "'*.lan'", "'anki:8000'", "'http://anki'", "'a b'", "''", "'[::1]'"]
)
def test_invalid_allowed_hosts_are_rejected(tmp_path: Path, entry: str) -> None:
    """Wildcards, ports, URLs, spaces, brackets, and empty names are refused.

    Args:
        tmp_path: Temporary test folder.
        entry: Invalid list entry as YAML.
    """
    with pytest.raises(SettingsError, match="allowed_hosts"):
        load_settings(write(tmp_path, f"allowed_hosts: [{entry}]\n"))


def test_empty_allowed_hosts_are_rejected(tmp_path: Path) -> None:
    """At least one host name is required.

    Args:
        tmp_path: Temporary test folder.
    """
    with pytest.raises(SettingsError, match="allowed_hosts"):
        load_settings(write(tmp_path, "allowed_hosts: []\n"))


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
