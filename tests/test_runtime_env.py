"""Tests for the optional systemd environment file used by AS-016."""

import stat
from pathlib import Path

import pytest

from anki_studio.credentials import new_secret_key
from anki_studio.runtime_env import (
    RUNTIME_PASSWORD_HASH_ENV,
    RUNTIME_SESSION_SECRET_ENV,
    RUNTIME_SYNC_ENDPOINT_ENV,
    RUNTIME_SYNC_PASSWORD_ENV,
    RUNTIME_SYNC_USERNAME_ENV,
    RuntimeEnvironment,
    RuntimeEnvironmentError,
    encode_value,
    read_secret,
    read_value,
)

KEY = new_secret_key()


def environment_from(path: Path) -> dict[str, str]:
    """Read a test-only systemd environment file into a mapping.

    Args:
        path: File written by ``RuntimeEnvironment``.

    Returns:
        Environment variable names and their encoded values.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", maxsplit=1) for line in lines)


def test_runtime_file_is_private_and_encodes_every_mutable_value(tmp_path: Path) -> None:
    """Runtime settings replace all access values atomically; secrets are encrypted.

    Args:
        tmp_path: Private temporary application directory.
    """
    runtime = RuntimeEnvironment(tmp_path, KEY)
    runtime.save(
        password_hash="scrypt:example",
        session_secret="session-secret-for-test",
        sync_endpoint="https://sync.example",
        sync_username="test user",
        sync_password="sync password $ with spaces",
    )

    content = runtime.path.read_text(encoding="utf-8")
    values = environment_from(runtime.path)

    assert stat.S_IMODE(runtime.path.stat().st_mode) == 0o600
    assert "sync password $ with spaces" not in content
    assert encode_value("sync password $ with spaces") not in content
    assert encode_value("session-secret-for-test") not in content
    assert read_value(values, RUNTIME_PASSWORD_HASH_ENV) == "scrypt:example"
    assert read_secret(values, RUNTIME_SESSION_SECRET_ENV, KEY) == "session-secret-for-test"
    assert read_value(values, RUNTIME_SYNC_ENDPOINT_ENV) == "https://sync.example"
    assert read_value(values, RUNTIME_SYNC_USERNAME_ENV) == "test user"
    assert read_secret(values, RUNTIME_SYNC_PASSWORD_ENV, KEY) == "sync password $ with spaces"


def test_saving_without_key_is_refused(tmp_path: Path) -> None:
    """Without ``ANKI_STUDIO_SECRET_KEY`` no runtime file is written.

    Args:
        tmp_path: Private temporary application directory.
    """
    runtime = RuntimeEnvironment(tmp_path, None)

    with pytest.raises(RuntimeEnvironmentError, match="ANKI_STUDIO_SECRET_KEY fehlt"):
        runtime.save(
            password_hash=None,
            session_secret="session-secret-for-test",
            sync_endpoint=None,
            sync_username=None,
            sync_password=None,
        )

    assert not runtime.path.exists()


def test_runtime_file_can_explicitly_clear_base_values(tmp_path: Path) -> None:
    """Empty encoded values remain distinct from an absent runtime override.

    Args:
        tmp_path: Private temporary application directory.
    """
    runtime = RuntimeEnvironment(tmp_path, KEY)
    runtime.save(
        password_hash=None,
        session_secret="session-secret-for-test",
        sync_endpoint=None,
        sync_username=None,
        sync_password=None,
    )

    values = environment_from(runtime.path)

    assert read_value(values, RUNTIME_SYNC_ENDPOINT_ENV) == ""
    assert read_value(values, RUNTIME_SYNC_USERNAME_ENV) == ""
    assert read_secret(values, RUNTIME_SYNC_PASSWORD_ENV, KEY) == ""


@pytest.mark.parametrize(
    ("name", "reader"),
    [
        (RUNTIME_SYNC_USERNAME_ENV, lambda env, name: read_value(env, name)),
        (RUNTIME_SYNC_PASSWORD_ENV, lambda env, name: read_secret(env, name, KEY)),
    ],
)
def test_invalid_runtime_value_is_rejected_without_echoing_it(name: str, reader) -> None:
    """Malformed values cannot be mistaken for a safe runtime configuration.

    Args:
        name: Runtime variable holding the malformed value.
        reader: Reader for plain or encrypted values.
    """
    malformed = "not a runtime value!"

    with pytest.raises(RuntimeEnvironmentError) as error:
        reader({name: malformed}, name)

    assert malformed not in str(error.value)


def test_encoder_uses_only_environment_file_safe_base64() -> None:
    """Encoded values contain neither whitespace nor shell metacharacters."""
    encoded = encode_value("sync password $ with spaces\n")

    assert encoded == "c3luYyBwYXNzd29yZCAkIHdpdGggc3BhY2VzCg=="
