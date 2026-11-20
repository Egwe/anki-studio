"""Load the settings of Anki Studio itself from ``studio.yaml``.

These settings describe the web application (listening address, later data
paths and the sync endpoint). Card generation settings stay in the
generator's own YAML file; secrets only come from the environment.
"""

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

CONFIG_ENV = "ANKI_STUDIO_CONFIG"
FORBIDDEN_HOST_CHARACTERS = frozenset("/*[]@ \t")


class SettingsError(Exception):
    """Report an unreadable or invalid settings file in plain words."""


class StudioSettings(BaseModel):
    """Hold the validated settings of the web application.

    Attributes:
        host: Address uvicorn listens on, for example ``0.0.0.0`` in the
            container or ``127.0.0.1`` for local development.
        port: TCP port of the web interface, 1–65535.
        allowed_hosts: Host names and IP addresses the browser may use to
            reach Anki Studio, without port; compared case-insensitively.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)
    allowed_hosts: tuple[str, ...] = Field(default=("localhost", "127.0.0.1"), min_length=1)

    @field_validator("allowed_hosts")
    @classmethod
    def _normalize_hosts(cls, hosts: tuple[str, ...]) -> tuple[str, ...]:
        """Lower-case the host names and reject wildcards, ports, and paths.

        Args:
            hosts: Configured host names.

        Returns:
            The trimmed, lower-case host names.

        Raises:
            ValueError: If an entry is empty or contains ``/``, ``*``,
                brackets, ``@``, or whitespace, or ends with a port.
        """
        normalized = tuple(host.strip().lower() for host in hosts)
        for host in normalized:
            if not host or FORBIDDEN_HOST_CHARACTERS & set(host) or _has_port(host):
                raise ValueError(f"ungültiger Hostname {host!r}: nur Name oder IP-Adresse")
        return normalized


def settings_path(explicit: Path | None) -> Path | None:
    """Choose the settings file from an explicit path or the environment.

    Args:
        explicit: Path given on the command line, or None.

    Returns:
        ``explicit`` if given, otherwise the path in ``ANKI_STUDIO_CONFIG``,
        otherwise None for built-in defaults.
    """
    if explicit is not None:
        return explicit
    value = os.environ.get(CONFIG_ENV)
    return Path(value) if value else None


def load_settings(path: Path | None) -> StudioSettings:
    """Read and validate the settings file.

    Args:
        path: YAML file to read, or None to use the built-in defaults.

    Returns:
        Validated, immutable settings.

    Raises:
        SettingsError: If the file cannot be read, is no YAML mapping, or
            contains unknown keys or invalid values.
    """
    if path is None:
        return StudioSettings()
    data = _read_mapping(path)
    try:
        return StudioSettings.model_validate(data)
    except ValidationError as error:
        raise SettingsError(f"Ungültige Einstellungen in {path}: {_describe(error)}") from error


def _has_port(host: str) -> bool:
    """Detect a ``name:port`` entry while allowing bare IPv6 addresses.

    Args:
        host: Lower-case host entry.

    Returns:
        True for exactly one colon followed by digits, such as ``name:8000``.
    """
    _, colon, port = host.partition(":")
    return bool(colon) and ":" not in port and port.isdigit()


def _read_mapping(path: Path) -> dict[str, Any]:
    """Parse a YAML file that must contain a mapping or nothing.

    Args:
        path: YAML file to read.

    Returns:
        The parsed mapping; an empty file yields an empty mapping.

    Raises:
        SettingsError: If the file is unreadable, no valid YAML, or not a
            mapping.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise SettingsError(f"Einstellungsdatei nicht lesbar: {path} ({error.strerror})") from error
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise SettingsError(f"Einstellungsdatei ist kein gültiges YAML: {path}") from error
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SettingsError(f"Einstellungsdatei muss Schlüssel und Werte enthalten: {path}")
    return data


def _describe(error: ValidationError) -> str:
    """Summarize validation errors as ``key: message`` pairs.

    Args:
        error: Pydantic validation error of ``StudioSettings``.

    Returns:
        One line listing every invalid or unknown key with its message.
    """
    parts = []
    for item in error.errors():
        key = ".".join(str(part) for part in item["loc"]) or "(Datei)"
        parts.append(f"{key}: {item['msg']}")
    return "; ".join(parts)
