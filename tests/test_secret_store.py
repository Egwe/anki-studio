"""Tests for the encrypted store of API keys (AS-035)."""

from pathlib import Path

import pytest

from anki_studio.credentials import new_secret_key
from anki_studio.secret_store import (
    STORE_FILE,
    SecretSource,
    SecretStore,
    SecretStoreError,
    valid_name,
)

VALUE = "sk-test-0123456789abcdefghij"


def make_store(tmp_path: Path, environ: dict[str, str], key: str | None = "new") -> SecretStore:
    """Create a store in the test folder with its own environment.

    Args:
        tmp_path: Temporary test folder.
        environ: Simulated process environment, changed by the store.
        key: Fernet key, ``"new"`` for a fresh one, or None.

    Returns:
        The store for ``<tmp_path>/secrets.enc``.
    """
    secret_key = new_secret_key() if key == "new" else key
    return SecretStore(tmp_path / STORE_FILE, secret_key, environ)


@pytest.mark.parametrize(
    ("name", "allowed"),
    [
        ("OPENAI_API_KEY", True),
        ("HF_TOKEN", True),
        ("CUSTOM_LLM_API_KEY", True),
        ("A_KEY", True),
        ("PATH", False),
        ("LD_PRELOAD", False),
        ("PYTHONPATH", False),
        ("openai_api_key", False),
        ("ANKI_STUDIO_SECRET_KEY", False),
        ("OPENAI_API_KEY\nPATH", False),
        ("", False),
    ],
)
def test_only_key_like_names_are_allowed(name: str, allowed: bool) -> None:
    """The interface can never set arbitrary environment variables.

    Args:
        name: Proposed variable.
        allowed: Expected decision.
    """
    assert valid_name(name) is allowed


def test_set_encrypts_and_updates_environment(tmp_path: Path) -> None:
    """A stored key lands encrypted on disk and in the environment.

    Args:
        tmp_path: Temporary test folder.
    """
    environ: dict[str, str] = {}
    store = make_store(tmp_path, environ)

    store.set("OPENAI_API_KEY", f"  {VALUE}  ")

    raw = (tmp_path / STORE_FILE).read_bytes()
    assert VALUE.encode() not in raw
    assert (tmp_path / STORE_FILE).stat().st_mode & 0o777 == 0o600
    assert environ["OPENAI_API_KEY"] == VALUE
    status = store.status(["OPENAI_API_KEY"])[0]
    assert status.source is SecretSource.STORED
    assert status.updated_at is not None
    assert VALUE not in repr(status)


def test_stored_keys_survive_a_restart(tmp_path: Path) -> None:
    """A new store with the same key applies the saved values.

    Args:
        tmp_path: Temporary test folder.
    """
    key = new_secret_key()
    make_store(tmp_path, {}, key).set("GEMINI_API_KEY", VALUE)
    environ: dict[str, str] = {}

    applied = make_store(tmp_path, environ, key).apply()

    assert applied == ["GEMINI_API_KEY"]
    assert environ["GEMINI_API_KEY"] == VALUE


def test_environment_file_wins(tmp_path: Path) -> None:
    """Variables set before start are read-only and not overwritten.

    Args:
        tmp_path: Temporary test folder.
    """
    key = new_secret_key()
    make_store(tmp_path, {}, key).set("OPENAI_API_KEY", VALUE)
    environ = {"OPENAI_API_KEY": "aus-der-env-datei"}
    store = make_store(tmp_path, environ, key)

    store.apply()

    assert environ["OPENAI_API_KEY"] == "aus-der-env-datei"
    assert store.status(["OPENAI_API_KEY"])[0].source is SecretSource.ENVIRONMENT
    with pytest.raises(SecretStoreError, match="Umgebungsdatei"):
        store.set("OPENAI_API_KEY", VALUE)
    with pytest.raises(SecretStoreError, match="Umgebungsdatei"):
        store.delete("OPENAI_API_KEY")


def test_delete_removes_key(tmp_path: Path) -> None:
    """Deleting removes the key from the file and the environment.

    Args:
        tmp_path: Temporary test folder.
    """
    environ: dict[str, str] = {}
    store = make_store(tmp_path, environ)
    store.set("MISTRAL_API_KEY", VALUE)

    assert store.delete("MISTRAL_API_KEY")
    assert not store.delete("MISTRAL_API_KEY")
    assert "MISTRAL_API_KEY" not in environ
    assert store.status(["MISTRAL_API_KEY"])[0].source is SecretSource.MISSING


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("PATH", VALUE, "kein erlaubter Name"),
        ("OPENAI_API_KEY", "   ", "Bitte einen Schlüssel"),
        ("OPENAI_API_KEY", "x" * 1001, "länger als 1000"),
        ("OPENAI_API_KEY", "sk-abc\nPATH=/tmp", "Zeilenumbrüche"),
    ],
)
def test_invalid_changes_are_refused(tmp_path: Path, name: str, value: str, message: str) -> None:
    """Bad names and values are refused without echoing the value.

    Args:
        tmp_path: Temporary test folder.
        name: Variable to set.
        value: Value to store.
        message: Expected part of the message.
    """
    environ: dict[str, str] = {}
    store = make_store(tmp_path, environ)

    with pytest.raises(SecretStoreError, match=message) as error:
        store.set(name, value)

    assert value.strip() not in str(error.value) or not value.strip()
    assert environ == {}
    assert not (tmp_path / STORE_FILE).exists()


def test_without_key_nothing_can_be_stored(tmp_path: Path) -> None:
    """Without ``ANKI_STUDIO_SECRET_KEY`` there is no plain-text fallback.

    Args:
        tmp_path: Temporary test folder.
    """
    store = make_store(tmp_path, {}, key=None)

    assert not store.available
    with pytest.raises(SecretStoreError, match="ANKI_STUDIO_SECRET_KEY fehlt"):
        store.set("OPENAI_API_KEY", VALUE)
    assert store.status(["OPENAI_API_KEY"])[0].source is SecretSource.MISSING


def test_wrong_key_is_reported(tmp_path: Path) -> None:
    """A changed encryption key is detected instead of returning garbage.

    Args:
        tmp_path: Temporary test folder.
    """
    make_store(tmp_path, {}).set("OPENAI_API_KEY", VALUE)

    with pytest.raises(SecretStoreError, match="nicht entschlüsseln"):
        make_store(tmp_path, {}).apply()


def test_status_lists_requested_and_stored_names(tmp_path: Path) -> None:
    """Status covers the requested names and every stored one, sorted.

    Args:
        tmp_path: Temporary test folder.
    """
    store = make_store(tmp_path, {})
    store.set("XAI_API_KEY", VALUE)

    names = [status.name for status in store.status(["OPENAI_API_KEY", "PATH"])]

    assert names == ["OPENAI_API_KEY", "XAI_API_KEY"]
