"""Persist daily access settings in a private systemd environment file.

The service unit reads this optional file after its administrator-managed
environment file.  Its values therefore override the initial login and sync
setup without putting secrets in YAML, jobs, or logs.  Plain values (login
hash, endpoint, user name) are Base64 only for safe systemd
``EnvironmentFile`` syntax.  The session secret and the sync password are
Fernet tokens under ``ANKI_STUDIO_SECRET_KEY`` like the API keys of AS-035,
so a copy of the data directory without ``/etc/anki-studio/env`` reveals
neither.  File permissions (0600) remain the first boundary.
"""

import base64
import binascii
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

RUNTIME_ENV_FILE = "runtime.env"
RUNTIME_PASSWORD_HASH_ENV = "ANKI_STUDIO_RUNTIME_PASSWORD_HASH_B64"
RUNTIME_SESSION_SECRET_ENV = "ANKI_STUDIO_RUNTIME_SESSION_SECRET_ENC"
RUNTIME_SYNC_ENDPOINT_ENV = "ANKI_STUDIO_RUNTIME_SYNC_ENDPOINT_B64"
RUNTIME_SYNC_USERNAME_ENV = "ANKI_STUDIO_RUNTIME_SYNC_USERNAME_B64"
RUNTIME_SYNC_PASSWORD_ENV = "ANKI_STUDIO_RUNTIME_SYNC_PASSWORD_ENC"
SECRET_KEY_NAME = "ANKI_STUDIO_SECRET_KEY"


class RuntimeEnvironmentError(Exception):
    """Report a malformed or undecryptable runtime value without exposing it."""


class RuntimeEnvironment:
    """Write the optional service environment for daily access settings.

    Args:
        data_dir: Private application data directory.  The file is created as
            ``runtime.env`` below this directory with mode ``0600``.
        secret_key: Fernet key from ``ANKI_STUDIO_SECRET_KEY`` that encrypts
            the session secret and the sync password, or None; then nothing
            can be saved.
    """

    def __init__(self, data_dir: Path, secret_key: str | None) -> None:
        """Remember the environment-file path below ``data_dir`` and the key.

        Args:
            data_dir: Private application data directory.
            secret_key: Checked Fernet key, or None.
        """
        self.path = data_dir / RUNTIME_ENV_FILE
        self._secret_key = secret_key

    def save(
        self,
        *,
        password_hash: str | None,
        session_secret: str,
        sync_endpoint: str | None,
        sync_username: str | None,
        sync_password: str | None,
    ) -> None:
        """Atomically replace all mutable login and sync values.

        Args:
            password_hash: Valid login hash, or None while login is disabled.
            session_secret: Session cookie signing secret.
            sync_endpoint: Valid sync endpoint, or None to disable sync.
            sync_username: Sync user name, or None while disabled.
            sync_password: Sync password, or None while disabled.

        Returns:
            None.

        Raises:
            RuntimeEnvironmentError: If no encryption key is configured; the
                file is left unchanged.
            OSError: If the private file cannot be created or replaced.
        """
        if self._secret_key is None:
            raise RuntimeEnvironmentError(
                f"{SECRET_KEY_NAME} fehlt; ohne ihn speichert Anki Studio keine Zugangsdaten."
            )
        fernet = Fernet(self._secret_key)
        values = (
            (RUNTIME_PASSWORD_HASH_ENV, encode_value(password_hash)),
            (RUNTIME_SESSION_SECRET_ENV, encrypt_value(fernet, session_secret)),
            (RUNTIME_SYNC_ENDPOINT_ENV, encode_value(sync_endpoint)),
            (RUNTIME_SYNC_USERNAME_ENV, encode_value(sync_username)),
            (RUNTIME_SYNC_PASSWORD_ENV, encrypt_value(fernet, sync_password)),
        )
        content = "".join(f"{name}={value}\n" for name, value in values)
        _atomic_write(self.path, content)


def encode_value(value: str | None) -> str:
    """Encode a possibly empty value for systemd's environment-file syntax.

    Args:
        value: Text to persist, or None for an empty override.

    Returns:
        URL-safe Base64 text without whitespace or shell syntax.
    """
    raw = (value or "").encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def encrypt_value(fernet: Fernet, value: str | None) -> str:
    """Encrypt a secret for the environment file.

    Args:
        fernet: Cipher built from ``ANKI_STUDIO_SECRET_KEY``.
        value: Secret text, or None for an empty override.

    Returns:
        A Fernet token (URL-safe Base64, safe in an ``EnvironmentFile``), or
        an empty string for a missing or empty value.
    """
    if not value:
        return ""
    return fernet.encrypt(value.encode("utf-8")).decode("ascii")


def read_secret(environ: Mapping[str, str], name: str, secret_key: str | None) -> str | None:
    """Read and decrypt one secret runtime value.

    Args:
        environ: Process environment supplied by systemd or a test.
        name: Runtime variable name ending in ``_ENC``.
        secret_key: Checked Fernet key from ``ANKI_STUDIO_SECRET_KEY``, or None.

    Returns:
        The decrypted text, an empty string for an explicit empty value, or
        None when ``name`` is absent.

    Raises:
        RuntimeEnvironmentError: If the value is set but the key is missing
            or does not decrypt it.  Neither value nor key appear in the error.
    """
    token = environ.get(name)
    if token is None or not token:
        return token
    if secret_key is None:
        raise RuntimeEnvironmentError(f"{name} ist gesetzt, aber {SECRET_KEY_NAME} fehlt.")
    try:
        return Fernet(secret_key).decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeError) as error:
        raise RuntimeEnvironmentError(
            f"{name} lässt sich mit {SECRET_KEY_NAME} nicht entschlüsseln."
        ) from error


def read_value(environ: Mapping[str, str], name: str) -> str | None:
    """Read one encoded runtime value, retaining the missing/empty distinction.

    Args:
        environ: Process environment supplied by systemd or a test.
        name: Runtime variable name ending in ``_B64``.

    Returns:
        Decoded text, including an empty string for an explicit empty value,
        or None when ``name`` is absent.

    Raises:
        RuntimeEnvironmentError: If the configured value is not valid UTF-8
            Base64.  Its content is never included in the error.
    """
    encoded = environ.get(name)
    if encoded is None:
        return None
    try:
        decoded = base64.b64decode(encoded, altchars=b"-_", validate=True)
        return decoded.decode("utf-8")
    except (UnicodeDecodeError, binascii.Error) as error:
        raise RuntimeEnvironmentError(f"{name} ist ungültig.") from error


def _atomic_write(path: Path, content: str) -> None:
    """Write a private environment file without exposing a partial version.

    Args:
        path: Destination below the service's private data directory.
        content: Fully encoded environment-file content.

    Returns:
        None.

    Raises:
        OSError: If the parent cannot be created or the replacement fails.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    handle = os.fdopen(descriptor, "w", encoding="utf-8")
    try:
        with handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except OSError:
        try:
            Path(temporary_name).unlink()
        except FileNotFoundError:
            pass
        raise
