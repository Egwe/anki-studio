"""Shared fixtures for the Anki Studio tests."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from anki_studio.app import create_app
from anki_studio.credentials import Credentials
from anki_studio.passwords import hash_password
from anki_studio.routes import login
from anki_studio.settings import StudioSettings

PASSWORD = "richtig-geheim"
PASSWORD_HASH = hash_password(PASSWORD)
SESSION_SECRET = "test-session-secret-" + "x" * 20
TEST_SETTINGS = StudioSettings(allowed_hosts=("testserver",))


@pytest.fixture(autouse=True)
def no_login_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip the delay after wrong passwords to keep tests fast.

    Args:
        monkeypatch: Pytest fixture for replacing attributes.
    """
    monkeypatch.setattr(login, "FAILED_LOGIN_DELAY_SECONDS", 0)


def make_client(password_hash: str | None = PASSWORD_HASH) -> TestClient:
    """Create a test client for an application with test secrets.

    Args:
        password_hash: Configured password hash, or None for "not set".

    Returns:
        A test client for host ``testserver``; the caller closes it.
    """
    credentials = Credentials(password_hash=password_hash, session_secret=SESSION_SECRET)
    return TestClient(create_app(TEST_SETTINGS, credentials))


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Provide an anonymous test client.

    Yields:
        A ``TestClient`` without session; closed afterwards.
    """
    with make_client() as test_client:
        yield test_client


@pytest.fixture
def auth_client() -> Iterator[TestClient]:
    """Provide a test client that has logged in with the test password.

    Yields:
        A ``TestClient`` with a valid session cookie; closed afterwards.
    """
    with make_client() as test_client:
        response = test_client.post("/login", data={"password": PASSWORD}, follow_redirects=False)
        assert response.status_code == 303
        yield test_client
