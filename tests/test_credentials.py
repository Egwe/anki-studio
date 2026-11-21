"""Tests for reading the login secrets from the environment."""

import pytest

from anki_studio.credentials import (
    PASSWORD_HASH_ENV,
    SECRET_KEY_ENV,
    SESSION_SECRET_ENV,
    SYNC_PASSWORD_ENV,
    SYNC_USERNAME_ENV,
    CredentialsError,
    load_credentials,
    new_secret_key,
)
from anki_studio.passwords import hash_password
from anki_studio.runtime_env import (
    RUNTIME_PASSWORD_HASH_ENV,
    RUNTIME_SESSION_SECRET_ENV,
    RUNTIME_SYNC_PASSWORD_ENV,
    RUNTIME_SYNC_USERNAME_ENV,
    encode_value,
)

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


def test_reads_valid_secret_key() -> None:
    """A Fernet key is taken over and hidden from ``repr``."""
    key = new_secret_key()

    credentials = load_credentials({SECRET_KEY_ENV: key, SESSION_SECRET_ENV: SECRET})

    assert credentials.secret_key == key
    assert key not in repr(credentials)


def test_missing_secret_key_is_allowed() -> None:
    """Without the key the app starts; API keys just cannot be stored."""
    assert load_credentials({SESSION_SECRET_ENV: SECRET}).secret_key is None


def test_reads_sync_credentials_without_showing_them() -> None:
    """Sync credentials remain environment-only and excluded from ``repr``."""
    credentials = load_credentials(
        {
            SESSION_SECRET_ENV: SECRET,
            SYNC_USERNAME_ENV: "studio",
            SYNC_PASSWORD_ENV: "test-geheim",
        }
    )

    assert credentials.sync_username == "studio"
    assert credentials.sync_password == "test-geheim"
    assert "test-geheim" not in repr(credentials)


def test_runtime_environment_overrides_base_access_values() -> None:
    """The daily environment wins over initial login and sync setup."""
    initial_hash = hash_password("erstes-passwort")
    runtime_hash = hash_password("neues-passwort")
    environment = {
        PASSWORD_HASH_ENV: initial_hash,
        SESSION_SECRET_ENV: SECRET,
        SYNC_USERNAME_ENV: "initial-user",
        SYNC_PASSWORD_ENV: "initial-password",
        RUNTIME_PASSWORD_HASH_ENV: encode_value(runtime_hash),
        RUNTIME_SESSION_SECRET_ENV: encode_value("runtime-" + "s" * 40),
        RUNTIME_SYNC_USERNAME_ENV: encode_value("runtime-user"),
        RUNTIME_SYNC_PASSWORD_ENV: encode_value("runtime-password"),
    }

    credentials = load_credentials(environment)

    assert credentials.password_hash == runtime_hash
    assert credentials.session_secret == "runtime-" + "s" * 40
    assert credentials.sync_username == "runtime-user"
    assert credentials.sync_password == "runtime-password"


def test_invalid_secret_key_is_rejected_without_value() -> None:
    """A malformed key stops the start; the message hides the value."""
    with pytest.raises(CredentialsError, match=SECRET_KEY_ENV) as error:
        load_credentials({SECRET_KEY_ENV: "kein-fernet-schluessel"})

    assert "kein-fernet-schluessel" not in str(error.value)
