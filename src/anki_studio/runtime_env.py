"""Persist daily access settings in a private systemd environment file.

The service unit reads this optional file after its administrator-managed
environment file.  Its encoded values therefore override the initial login
and sync setup without putting secrets in YAML, jobs, or logs.  Encoding is
only for safe systemd ``EnvironmentFile`` syntax; file permissions remain the
security boundary.
"""

import base64
import binascii
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

RUNTIME_ENV_FILE = "runtime.env"
RUNTIME_PASSWORD_HASH_ENV = "ANKI_STUDIO_RUNTIME_PASSWORD_HASH_B64"
RUNTIME_SESSION_SECRET_ENV = "ANKI_STUDIO_RUNTIME_SESSION_SECRET_B64"
RUNTIME_SYNC_ENDPOINT_ENV = "ANKI_STUDIO_RUNTIME_SYNC_ENDPOINT_B64"
RUNTIME_SYNC_USERNAME_ENV = "ANKI_STUDIO_RUNTIME_SYNC_USERNAME_B64"
RUNTIME_SYNC_PASSWORD_ENV = "ANKI_STUDIO_RUNTIME_SYNC_PASSWORD_B64"


class RuntimeEnvironmentError(Exception):
    """Report a malformed runtime environment value without exposing it."""


class RuntimeEnvironment:
    """Write the optional service environment for daily access settings.

    Args:
        data_dir: Private application data directory.  The file is created as
            ``runtime.env`` below this directory with mode ``0600``.
    """

    def __init__(self, data_dir: Path) -> None:
        """Remember the environment-file path below ``data_dir``.

        Args:
            data_dir: Private application data directory.
        """
        self.path = data_dir / RUNTIME_ENV_FILE

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
            OSError: If the private file cannot be created or replaced.
        """
        values = (
            (RUNTIME_PASSWORD_HASH_ENV, password_hash),
            (RUNTIME_SESSION_SECRET_ENV, session_secret),
            (RUNTIME_SYNC_ENDPOINT_ENV, sync_endpoint),
            (RUNTIME_SYNC_USERNAME_ENV, sync_username),
            (RUNTIME_SYNC_PASSWORD_ENV, sync_password),
        )
        content = "".join(f"{name}={encode_value(value)}\n" for name, value in values)
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
