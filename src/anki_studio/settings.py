"""Load the settings of Anki Studio itself from ``studio.yaml``.

These settings describe the web application (listening address, allowed
host names, data folder, job retention; later the sync endpoint). Card
generation settings stay in the generator's own YAML file; secrets only
come from the environment.
"""

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from anki_studio.runtime_env import RUNTIME_SYNC_ENDPOINT_ENV, RuntimeEnvironmentError, read_value

CONFIG_ENV = "ANKI_STUDIO_CONFIG"
FORBIDDEN_HOST_CHARACTERS = frozenset("/*[]@ \t")
SYNC_SCHEMES = frozenset({"http", "https"})


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
        data_dir: Folder for jobs and later the collection; a relative path
            is resolved next to ``studio.yaml`` (without file: the working
            directory) by ``load_settings``.
        job_retention_days: Finished jobs older than this many days are
            deleted, 1–3650.
        generator_config: YAML file of the generator (profiles, defaults,
            ``pdf_conversion``); relative paths are resolved like
            ``data_dir``; None means ``<data_dir>/generator.yaml``, where
            Anki Studio may write it (AS-015).
        sync_endpoint: HTTP(S) endpoint of the Anki sync server, or None
            until sync is configured. Credentials remain environment-only.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)
    allowed_hosts: tuple[str, ...] = Field(default=("localhost", "127.0.0.1"), min_length=1)
    data_dir: Path = Path("data")
    job_retention_days: int = Field(default=14, ge=1, le=3650)
    generator_config: Path | None = None
    sync_endpoint: str | None = Field(default=None, max_length=500)

    @property
    def generator_path(self) -> Path:
        """Return the generator YAML that Anki Studio uses.

        Returns:
            ``generator_config`` if set, otherwise ``<data_dir>/generator.yaml``.
        """
        return self.generator_config or self.data_dir / "generator.yaml"

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

    @field_validator("sync_endpoint")
    @classmethod
    def _check_sync_endpoint(cls, endpoint: str | None) -> str | None:
        """Accept only a complete HTTP(S) sync-server endpoint.

        Args:
            endpoint: Endpoint from ``studio.yaml``, or None.

        Returns:
            Trimmed endpoint without a query or fragment, or None.

        Raises:
            ValueError: If the endpoint is blank, has another scheme, lacks a
                host, embeds credentials, or includes query/fragment data.
        """
        return validate_sync_endpoint(endpoint)


def validate_sync_endpoint(endpoint: str | None) -> str | None:
    """Accept a complete HTTP(S) sync-server endpoint without credentials.

    Args:
        endpoint: Candidate endpoint, or None to disable synchronization.

    Returns:
        Trimmed endpoint without query or fragment, or None.

    Raises:
        ValueError: If the endpoint is blank, has another scheme, lacks a
            host, embeds credentials, or includes query/fragment data.
    """
    if endpoint is None:
        return None
    candidate = endpoint.strip()
    parsed = urlsplit(candidate)
    if (
        not candidate
        or parsed.scheme not in SYNC_SCHEMES
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("muss eine HTTP(S)-Adresse ohne Zugangsdaten sein")
    return candidate


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
        Validated, immutable settings with absolute ``data_dir`` and
        ``generator_config``.

    Raises:
        SettingsError: If the file cannot be read, is no YAML mapping, or
            contains unknown keys or invalid values.
    """
    if path is None:
        settings = StudioSettings()
        base = Path.cwd()
    else:
        data = _read_mapping(path)
        try:
            settings = StudioSettings.model_validate(data)
        except ValidationError as error:
            raise SettingsError(f"Ungültige Einstellungen in {path}: {_describe(error)}") from error
        base = path.absolute().parent
    try:
        endpoint = read_value(os.environ, RUNTIME_SYNC_ENDPOINT_ENV)
    except RuntimeEnvironmentError as error:
        raise SettingsError(str(error)) from error
    if endpoint is not None:
        try:
            settings = settings.model_copy(
                update={"sync_endpoint": validate_sync_endpoint(endpoint or None)}
            )
        except ValueError as error:
            raise SettingsError(
                f"Ungültige Laufzeit-Einstellung: sync_endpoint: {error}"
            ) from error
    return _with_absolute_paths(settings, base)


def _with_absolute_paths(settings: StudioSettings, base: Path) -> StudioSettings:
    """Resolve relative ``data_dir`` and ``generator_config`` against a folder.

    Args:
        settings: Validated settings.
        base: Folder of ``studio.yaml``, or the working directory.

    Returns:
        The settings with absolute paths; an unset ``generator_config``
        stays unset (see ``generator_path``).
    """
    data_dir = base / settings.data_dir
    generator_config = base / settings.generator_config if settings.generator_config else None
    return settings.model_copy(update={"data_dir": data_dir, "generator_config": generator_config})


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
