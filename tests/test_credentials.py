"""Tests for reading the login secrets from the environment."""

import pytest

from anki_studio.credentials import (
    PASSWORD_HASH_ENV,
    SESSION_SECRET_ENV,
    CredentialsError,
    load_credentials,
)
from anki_studio.passwords import hash_password

SECRET = "s" * 40


def test_reads_hash_and_secret() -> None:
    """Configured values are taken over unchanged."""
    encoded = hash_password("richtig-geheim")

    credentials = load_credentials({PASSWORD_HASH_ENV: encoded, SESSION_SECRET_ENV: SECRET})

    assert credentials.password_hash == encoded
    assert credentials.session_secret == SECRET
    assert not credentials.temporary_secret


def test_missing_values() -> None:
    """Without values nobody can log in and a temporary key is generated."""
    credentials = load_credentials({PASSWORD_HASH_ENV: " ", SESSION_SECRET_ENV: ""})

    assert credentials.password_hash is None
    assert credentials.temporary_secret
    assert len(credentials.session_secret) >= 32


def test_invalid_hash_is_rejected_without_value() -> None:
    """A broken hash stops the start; the message hides the value."""
    with pytest.raises(CredentialsError, match=PASSWORD_HASH_ENV) as error:
        load_credentials({PASSWORD_HASH_ENV: "scrypt:geheimer-wert"})

    assert "geheimer-wert" not in str(error.value)


def test_short_session_secret_is_rejected() -> None:
    """Session keys below 32 characters are refused."""
    with pytest.raises(CredentialsError, match="32 Zeichen"):
        load_credentials({SESSION_SECRET_ENV: "zu-kurz"})


def test_repr_hides_secrets() -> None:
    """Printing the credentials never shows hash or key."""
    encoded = hash_password("richtig-geheim")

    text = repr(load_credentials({PASSWORD_HASH_ENV: encoded, SESSION_SECRET_ENV: SECRET}))

    assert encoded not in text
    assert SECRET not in text
