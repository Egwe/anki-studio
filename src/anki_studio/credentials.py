"""Read the login secrets of Anki Studio from the environment.

Secrets never appear in ``studio.yaml``: in the container they come from
``/etc/anki-studio/env`` (systemd ``EnvironmentFile``), locally from a
``.env`` file passed with ``uv run --env-file .env``.
"""

import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field

from anki_studio.passwords import PasswordHashError, parse_hash

PASSWORD_HASH_ENV = "ANKI_STUDIO_PASSWORD_HASH"
SESSION_SECRET_ENV = "ANKI_STUDIO_SESSION_SECRET"
MIN_SESSION_SECRET_LENGTH = 32


class CredentialsError(Exception):
    """Report an invalid secret without revealing its value."""


@dataclass(frozen=True)
class Credentials:
    """Hold the login secrets; their values are excluded from ``repr``.

    Attributes:
        password_hash: Stored scrypt hash, or None while no password is set;
            then nobody can log in.
        session_secret: Key that signs the session cookie.
        temporary_secret: True if the session key was generated at start-up
            because none was configured; sessions then end with a restart.
    """

    password_hash: str | None = field(repr=False)
    session_secret: str = field(repr=False)
    temporary_secret: bool = False


def load_credentials(environ: Mapping[str, str]) -> Credentials:
    """Read and check the password hash and the session key.

    Empty values count as missing. A missing password hash is allowed so the
    login page can explain how to set one; a missing session key is replaced
    by a random temporary key.

    Args:
        environ: Environment variables, usually ``os.environ``.

    Returns:
        The checked credentials.

    Raises:
        CredentialsError: If the password hash is malformed or the session
            key is shorter than 32 characters.
    """
    password_hash = environ.get(PASSWORD_HASH_ENV, "").strip() or None
    if password_hash is not None:
        _check_hash(password_hash)
    session_secret = environ.get(SESSION_SECRET_ENV, "").strip()
    if not session_secret:
        return Credentials(password_hash, secrets.token_urlsafe(32), temporary_secret=True)
    if len(session_secret) < MIN_SESSION_SECRET_LENGTH:
        raise CredentialsError(
            f"{SESSION_SECRET_ENV} braucht mindestens {MIN_SESSION_SECRET_LENGTH} Zeichen."
        )
    return Credentials(password_hash, session_secret)


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
