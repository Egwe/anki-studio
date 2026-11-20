"""Keep provider API keys entered in the interface, encrypted (AS-035).

The keys are stored as one Fernet token (AES-128-CBC with HMAC-SHA256) in
``<data_dir>/secrets.enc``; the Fernet key comes only from the environment
file (``ANKI_STUDIO_SECRET_KEY``). Stored keys are copied into the process
environment, where the generator (``api_key_env``) and LiteLLM read them.
Values set in the environment file win and cannot be changed here. Values
are never returned to callers that render pages; only their status is.
"""

import json
import logging
import os
import re
import tempfile
import threading
from collections.abc import Iterable, MutableMapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

STORE_FILE = "secrets.enc"
NAME_PATTERN = re.compile(r"[A-Z][A-Z0-9_]{0,62}_(API_KEY|TOKEN|KEY)")
RESERVED_PREFIX = "ANKI_STUDIO_"
MAX_VALUE_LENGTH = 1000

logger = logging.getLogger(__name__)


class SecretStoreError(Exception):
    """Report a refused or impossible change in words for the user."""


class SecretSource(StrEnum):
    """Name where the value of a key variable comes from."""

    ENVIRONMENT = "environment"
    STORED = "stored"
    MISSING = "missing"


@dataclass(frozen=True)
class SecretStatus:
    """Describe one key variable without its value.

    Attributes:
        name: Environment variable, for example ``OPENAI_API_KEY``.
        source: Environment file, encrypted store, or missing.
        updated_at: Time of the last change in the store (UTC), or None.
    """

    name: str
    source: SecretSource
    updated_at: datetime | None = None


def valid_name(name: str) -> bool:
    """Tell whether a variable may be managed in the interface.

    Args:
        name: Proposed environment variable.

    Returns:
        True for upper-case names ending in ``_API_KEY``, ``_TOKEN`` or
        ``_KEY`` that do not start with ``ANKI_STUDIO_``; other variables
        such as ``PATH`` or ``LD_PRELOAD`` can never be set this way.
    """
    return NAME_PATTERN.fullmatch(name) is not None and not name.startswith(RESERVED_PREFIX)


class SecretStore:
    """Encrypted store of API keys with write-only access.

    Attributes:
        path: Encrypted file, ``<data_dir>/secrets.enc``.
        fixed: Variables already set in the environment at start; they win
            and are read-only here.
    """

    def __init__(
        self,
        path: Path,
        secret_key: str | None,
        environ: MutableMapping[str, str] | None = None,
    ) -> None:
        """Prepare the store; nothing is read or written yet.

        Args:
            path: Encrypted file.
            secret_key: Fernet key from ``ANKI_STUDIO_SECRET_KEY``, or None.
            environ: Process environment to update; ``os.environ`` if None.
                Variables set there now count as fixed.
        """
        self.path = path
        self._fernet = Fernet(secret_key) if secret_key else None
        self._environ = os.environ if environ is None else environ
        self._lock = threading.Lock()
        self.fixed = frozenset(
            name for name, value in self._environ.items() if value and valid_name(name)
        )

    @property
    def available(self) -> bool:
        """Tell whether keys can be stored.

        Returns:
            False without ``ANKI_STUDIO_SECRET_KEY``.
        """
        return self._fernet is not None

    def apply(self) -> list[str]:
        """Copy stored keys into the process environment.

        Fixed variables are left as they are.

        Returns:
            Names of the variables that were set.

        Raises:
            SecretStoreError: If the file cannot be decrypted.
        """
        entries = self._load()
        applied = [name for name in entries if name not in self.fixed]
        for name in applied:
            self._environ[name] = entries[name]["value"]
        return applied

    def status(self, names: Iterable[str]) -> list[SecretStatus]:
        """Describe variables and every stored one, sorted by name.

        Args:
            names: Variables of interest, for example from ``api_key_env``.

        Returns:
            One status per variable; values are never included.

        Raises:
            SecretStoreError: If the file cannot be decrypted.
        """
        entries = self._load() if self.available else {}
        wanted = sorted({*names, *entries})
        return [self._status(name, entries) for name in wanted if valid_name(name)]

    def set(self, name: str, value: str) -> None:
        """Store or replace a key and put it into the process environment.

        Args:
            name: Variable to set.
            value: The secret; surrounding whitespace is removed.

        Returns:
            None.

        Raises:
            SecretStoreError: If storing is unavailable, the name is not
                allowed or fixed, or the value is empty, too long, or
                contains line breaks or control characters.
        """
        self._check_writable(name)
        cleaned = value.strip()
        _check_value(cleaned)
        with self._lock:
            entries = self._load()
            entries[name] = {"value": cleaned, "updated_at": datetime.now(UTC).isoformat()}
            self._save(entries)
            self._environ[name] = cleaned
        logger.info("API-Schlüssel %s gespeichert", name)

    def delete(self, name: str) -> bool:
        """Remove a stored key from the file and the process environment.

        Args:
            name: Variable to remove.

        Returns:
            True if a stored key was removed, False if none was stored.

        Raises:
            SecretStoreError: If storing is unavailable or the name is not
                allowed or fixed.
        """
        self._check_writable(name)
        with self._lock:
            entries = self._load()
            if entries.pop(name, None) is None:
                return False
            self._save(entries)
            self._environ.pop(name, None)
        logger.info("API-Schlüssel %s gelöscht", name)
        return True

    def _status(self, name: str, entries: dict[str, dict[str, str]]) -> SecretStatus:
        """Describe one variable.

        Args:
            name: Valid variable name.
            entries: Decrypted store content.

        Returns:
            Its source and, for stored keys, the time of the last change.
        """
        if name in self.fixed:
            return SecretStatus(name, SecretSource.ENVIRONMENT)
        if name in entries:
            changed = datetime.fromisoformat(entries[name]["updated_at"])
            return SecretStatus(name, SecretSource.STORED, changed)
        return SecretStatus(name, SecretSource.MISSING)

    def _check_writable(self, name: str) -> None:
        """Refuse changes that the interface may not make.

        Args:
            name: Variable to change.

        Returns:
            None.

        Raises:
            SecretStoreError: With a German explanation.
        """
        if not self.available:
            raise SecretStoreError(
                "Speichern ist nicht möglich: ANKI_STUDIO_SECRET_KEY fehlt in der Umgebungsdatei."
            )
        if not valid_name(name):
            raise SecretStoreError(f"„{name}“ ist kein erlaubter Name für einen API-Schlüssel.")
        if name in self.fixed:
            raise SecretStoreError(
                f"{name} steht in der Umgebungsdatei und lässt sich hier nicht ändern."
            )

    def _load(self) -> dict[str, dict[str, str]]:
        """Decrypt the store file.

        Returns:
            Variable name to ``{"value", "updated_at"}``; empty without file
            or without key.

        Raises:
            SecretStoreError: If the file cannot be decrypted, for example
                after ``ANKI_STUDIO_SECRET_KEY`` was changed.
        """
        if self._fernet is None or not self.path.exists():
            return {}
        try:
            data = self._fernet.decrypt(self.path.read_bytes())
        except InvalidToken as error:
            raise SecretStoreError(
                f"{self.path.name} lässt sich nicht entschlüsseln; passt "
                "ANKI_STUDIO_SECRET_KEY noch zur Datei?"
            ) from error
        return json.loads(data)["secrets"]

    def _save(self, entries: dict[str, dict[str, str]]) -> None:
        """Encrypt and replace the store file atomically with mode 0600.

        Args:
            entries: Complete store content.

        Returns:
            None.
        """
        assert self._fernet is not None
        token = self._fernet.encrypt(json.dumps({"version": 1, "secrets": entries}).encode())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as temporary:
            temporary.write(token)
        os.replace(temporary.name, self.path)


def _check_value(value: str) -> None:
    """Refuse empty, overlong, or multi-line key values.

    Args:
        value: Stripped key value.

    Returns:
        None.

    Raises:
        SecretStoreError: With a message that never contains the value.
    """
    if not value:
        raise SecretStoreError("Bitte einen Schlüssel eingeben.")
    if len(value) > MAX_VALUE_LENGTH:
        raise SecretStoreError(f"Der Schlüssel ist länger als {MAX_VALUE_LENGTH} Zeichen.")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise SecretStoreError("Der Schlüssel enthält Zeilenumbrüche oder Steuerzeichen.")
