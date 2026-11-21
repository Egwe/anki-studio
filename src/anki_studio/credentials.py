"""Read the login secrets of Anki Studio from the environment.

Secrets never appear in ``studio.yaml``: in the container they come from
``/etc/anki-studio/env`` (systemd ``EnvironmentFile``), locally from a
``.env`` file passed with ``uv run --env-file .env``.
"""

import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field

from cryptography.fernet import Fernet

from anki_studio.passwords import PasswordHashError, parse_hash

PASSWORD_HASH_ENV = "ANKI_STUDIO_PASSWORD_HASH"
SESSION_SECRET_ENV = "ANKI_STUDIO_SESSION_SECRET"
SECRET_KEY_ENV = "ANKI_STUDIO_SECRET_KEY"
SYNC_USERNAME_ENV = "ANKI_STUDIO_SYNC_USERNAME"
SYNC_PASSWORD_ENV = "ANKI_STUDIO_SYNC_PASSWORD"
MIN_SESSION_SECRET_LENGTH = 32


class CredentialsError(Exception):
    """Report an invalid secret without revealing its value."""


@dataclass(frozen=True)
class Credentials:
    """Hold login and sync secrets; values are excluded from ``repr``.

    Attributes:
        password_hash: Stored scrypt hash, or None while no password is set;
            then nobody can log in.
        session_secret: Key that signs the session cookie.
        temporary_secret: True if the session key was generated at start-up
            because none was configured; sessions then end with a restart.
        secret_key: Fernet key that encrypts API keys entered in the
            interface (AS-035), or None; then they cannot be stored.
        sync_username: User name for the configured Anki sync server, or None
            while synchronization is not configured.
        sync_password: Password for ``sync_username``, or None; it is never
            persisted or exposed in a route, job, or template.
    """

    password_hash: str | None = field(repr=False)
    session_secret: str = field(repr=False)
    temporary_secret: bool = False
    secret_key: str | None = field(default=None, repr=False)
    sync_username: str | None = field(default=None, repr=False)
    sync_password: str | None = field(default=None, repr=False)


def load_credentials(environ: Mapping[str, str]) -> Credentials:
    """Read and check login, encryption, and sync credentials.

    Empty values count as missing. A missing password hash is allowed so the
    login page can explain how to set one; a missing session key is replaced
    by a random temporary key.

    Args:
        environ: Environment variables, usually ``os.environ``.

    Returns:
        The checked credentials.

    Raises:
        CredentialsError: If the password hash is malformed, the session key
            is shorter than 32 characters, or the encryption key is no valid
            Fernet key.
    """
    password_hash = environ.get(PASSWORD_HASH_ENV, "").strip() or None
    if password_hash is not None:
        _check_hash(password_hash)
    secret_key = environ.get(SECRET_KEY_ENV, "").strip() or None
    if secret_key is not None:
        _check_fernet_key(secret_key)
    sync_username = environ.get(SYNC_USERNAME_ENV, "").strip() or None
    sync_password = environ.get(SYNC_PASSWORD_ENV, "").strip() or None
    session_secret = environ.get(SESSION_SECRET_ENV, "").strip()
    if not session_secret:
        return Credentials(
            password_hash,
            secrets.token_urlsafe(32),
            temporary_secret=True,
            secret_key=secret_key,
            sync_username=sync_username,
            sync_password=sync_password,
        )
    if len(session_secret) < MIN_SESSION_SECRET_LENGTH:
        raise CredentialsError(
            f"{SESSION_SECRET_ENV} braucht mindestens {MIN_SESSION_SECRET_LENGTH} Zeichen."
        )
    return Credentials(
        password_hash,
        session_secret,
        secret_key=secret_key,
        sync_username=sync_username,
        sync_password=sync_password,
    )


def new_secret_key() -> str:
    """Generate a key for ``ANKI_STUDIO_SECRET_KEY``.

    Returns:
        A random Fernet key (32 bytes, URL-safe Base64).
    """
    return Fernet.generate_key().decode()


def _check_fernet_key(secret_key: str) -> None:
    """Make sure the encryption key has the Fernet format.

    Args:
        secret_key: Value of ``ANKI_STUDIO_SECRET_KEY``.

    Returns:
        None.

    Raises:
        CredentialsError: If the key is no URL-safe Base64 of 32 bytes; the
            message names the variable, never its value.
    """
    try:
        Fernet(secret_key)
    except ValueError as error:
        raise CredentialsError(
            f"{SECRET_KEY_ENV} ist ungültig: erwartet werden 32 Byte in URL-sicherem Base64."
        ) from error


def _check_hash(password_hash: str) -> None:
    """Make sure the configured password hash can be used.

    Args:
        password_hash: Value of ``ANKI_STUDIO_PASSWORD_HASH``.

    Returns:
        None.

    Raises:
        CredentialsError: If the hash is malformed; the message names the
            variable, never its value.
    """
    try:
        parse_hash(password_hash)
    except PasswordHashError as error:
        raise CredentialsError(f"{PASSWORD_HASH_ENV} ist ungültig: {error}") from error
