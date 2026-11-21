"""Shared fixtures and helpers for the Anki Studio tests."""

import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anki_studio.app import create_app
from anki_studio.credentials import Credentials, new_secret_key
from anki_studio.passwords import hash_password
from anki_studio.routes import login
from anki_studio.settings import StudioSettings

PASSWORD = "richtig-geheim"
PASSWORD_HASH = hash_password(PASSWORD)
SESSION_SECRET = "test-session-secret-" + "x" * 20
SECRET_KEY = new_secret_key()
GENERATOR_YAML = """
default_profile: lokal
generation:
  language: Englisch
pdf_conversion:
  models_dir: {models}
models:
  lokal:
    model: ollama/llama3.2
  nativ:
    model: openai/gpt-4o-mini
    api_key_env: TEST_STUDIO_KEY
    pdf_mode: native
"""


@pytest.fixture(autouse=True)
def restore_environment() -> Iterator[None]:
    """Undo changes the application makes to ``os.environ`` (stored keys).

    Yields:
        Control to the test; afterwards the environment is restored.
    """
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture(autouse=True)
def no_login_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the delay after wrong passwords to keep tests fast.

    Args:
        monkeypatch: Pytest fixture for replacing attributes.
    """
    monkeypatch.setattr(login, "FAILED_LOGIN_DELAY_SECONDS", 0)


@pytest.fixture
def studio_settings(tmp_path: Path) -> StudioSettings:
    """Provide settings with a private data folder and generator YAML.

    Args:
        tmp_path: Temporary test folder.

    Returns:
        Settings for host ``testserver`` with ``data_dir`` and
        ``generator_config`` below ``tmp_path``.
    """
    config = tmp_path / "config.yaml"
    config.write_text(GENERATOR_YAML.format(models=tmp_path / "models"), encoding="utf-8")
    return StudioSettings(
        allowed_hosts=("testserver",), data_dir=tmp_path / "data", generator_config=config
    )


def make_client(
    settings: StudioSettings,
    password_hash: str | None = PASSWORD_HASH,
    secret_key: str | None = SECRET_KEY,
) -> TestClient:
    """Create a test client for an application with test secrets.

    Args:
        settings: Settings of the application.
        password_hash: Configured password hash, or None for "not set".
        secret_key: Encryption key for API keys, or None for "not set".

    Returns:
        A test client; use it as context manager so the worker runs.
    """
    credentials = Credentials(
        password_hash=password_hash, session_secret=SESSION_SECRET, secret_key=secret_key
    )
    return TestClient(create_app(settings, credentials))


@pytest.fixture
def client(studio_settings: StudioSettings) -> Iterator[TestClient]:
    """Provide an anonymous test client with a running worker.

    Args:
        studio_settings: Settings of the test application.

    Yields:
        A ``TestClient`` without session; closed afterwards.
    """
    with make_client(studio_settings) as test_client:
        yield test_client


@pytest.fixture
def auth_client(studio_settings: StudioSettings) -> Iterator[TestClient]:
    """Provide a test client that has logged in with the test password.

    Args:
        studio_settings: Settings of the test application.

    Yields:
        A ``TestClient`` with a valid session cookie; closed afterwards.
    """
    with make_client(studio_settings) as test_client:
        response = test_client.post("/login", data={"password": PASSWORD}, follow_redirects=False)
        assert response.status_code == 303
        language = test_client.post(
            "/language", data={"locale": "de", "next": "/"}, follow_redirects=False
        )
        assert language.status_code == 303
        yield test_client


def wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    """Wait until a condition holds, failing the test after a timeout.

    Args:
        condition: Function that returns True once the expected state exists.
        timeout: Seconds to wait.
    """
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "Zustand nicht rechtzeitig erreicht"
        time.sleep(0.01)
