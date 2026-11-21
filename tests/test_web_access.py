"""Tests for daily login and synchronization setup in the web interface."""

from fastapi.testclient import TestClient

from anki_studio.credentials import load_credentials
from anki_studio.passwords import verify_password
from anki_studio.runtime_env import (
    RUNTIME_SYNC_ENDPOINT_ENV,
    RUNTIME_SYNC_PASSWORD_ENV,
    RUNTIME_SYNC_USERNAME_ENV,
    read_value,
)
from anki_studio.settings import StudioSettings, load_settings
from tests.conftest import PASSWORD, make_client

NEW_PASSWORD = "noch-sicherer-test"
SYNC_PASSWORD = "sync-test-passwort"


def runtime_environment(settings: StudioSettings) -> dict[str, str]:
    """Read the runtime file written below a test app's data directory.

    Args:
        settings: Settings whose data directory contains ``runtime.env``.

    Returns:
        Mapping suitable for ``load_credentials`` and ``read_value``.
    """
    path = settings.data_dir / "runtime.env"
    lines = path.read_text(encoding="utf-8").splitlines()
    return dict(line.split("=", maxsplit=1) for line in lines)


def test_access_page_needs_login(client: TestClient) -> None:
    """Anonymous browsers cannot inspect or change daily access settings.

    Args:
        client: Anonymous application client.
    """
    assert client.get("/settings/access", follow_redirects=False).status_code == 303
    response = client.post(
        "/settings/access/password",
        data={"password": NEW_PASSWORD, "confirmation": NEW_PASSWORD},
        follow_redirects=False,
    )

    assert response.headers["location"] == "/login"


def test_password_change_writes_hash_rotates_session_and_requests_restart(
    studio_settings: StudioSettings,
) -> None:
    """Changing a password never writes it verbatim and ends active sessions.

    Args:
        studio_settings: Settings with an isolated data directory.
    """
    restart_calls: list[None] = []
    with make_client(studio_settings) as client:
        client.app.state.request_restart = lambda: restart_calls.append(None)
        client.post("/login", data={"password": PASSWORD})

        response = client.post(
            "/settings/access/password",
            data={"password": NEW_PASSWORD, "confirmation": NEW_PASSWORD},
            follow_redirects=False,
        )

        previous_session = client.app.state.credentials.session_secret

    environment = runtime_environment(studio_settings)
    credentials = load_credentials(environment)
    raw = (studio_settings.data_dir / "runtime.env").read_text(encoding="utf-8")

    assert response.status_code == 303
    assert response.headers["location"] == "/login?changed=1"
    assert restart_calls == [None]
    assert credentials.password_hash is not None
    assert verify_password(NEW_PASSWORD, credentials.password_hash)
    assert credentials.session_secret != previous_session
    assert NEW_PASSWORD not in raw


def test_sync_change_overrides_endpoint_and_credentials_after_restart(
    studio_settings: StudioSettings, monkeypatch
) -> None:
    """A complete sync change is private, validated, and schedules a restart.

    Args:
        studio_settings: Settings with an isolated data directory.
        monkeypatch: Pytest helper that replaces process environment values.
    """
    restart_calls: list[None] = []
    with make_client(studio_settings) as client:
        client.app.state.request_restart = lambda: restart_calls.append(None)
        client.post("/login", data={"password": PASSWORD})

        response = client.post(
            "/settings/access/sync",
            data={
                "enabled": "true",
                "endpoint": "https://sync.example/anki",
                "username": "sync-user",
                "password": SYNC_PASSWORD,
            },
            follow_redirects=False,
        )

    environment = runtime_environment(studio_settings)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    settings = load_settings(None)
    credentials = load_credentials(environment)
    raw = (studio_settings.data_dir / "runtime.env").read_text(encoding="utf-8")

    assert response.status_code == 303
    assert restart_calls == [None]
    assert settings.sync_endpoint == "https://sync.example/anki"
    assert credentials.sync_username == "sync-user"
    assert credentials.sync_password == SYNC_PASSWORD
    assert read_value(environment, RUNTIME_SYNC_ENDPOINT_ENV) == "https://sync.example/anki"
    assert read_value(environment, RUNTIME_SYNC_USERNAME_ENV) == "sync-user"
    assert read_value(environment, RUNTIME_SYNC_PASSWORD_ENV) == SYNC_PASSWORD
    assert SYNC_PASSWORD not in raw


def test_sync_change_requires_all_values(auth_client: TestClient) -> None:
    """An enabled sync connection rejects a missing password without writing.

    Args:
        auth_client: Logged-in application client.
    """
    response = auth_client.post(
        "/settings/access/sync",
        data={"enabled": "true", "endpoint": "https://sync.example", "username": "sync-user"},
    )

    assert response.status_code == 400
    assert "Benutzername und Passwort sind erforderlich." in response.text


def test_sync_can_be_disabled(auth_client: TestClient, studio_settings: StudioSettings) -> None:
    """Removing the activation flag stores empty overrides for all sync values.

    Args:
        auth_client: Logged-in application client.
        studio_settings: Settings with the written runtime file.
    """
    restart_calls: list[None] = []
    auth_client.app.state.request_restart = lambda: restart_calls.append(None)

    response = auth_client.post("/settings/access/sync", data={}, follow_redirects=False)

    environment = runtime_environment(studio_settings)
    assert response.status_code == 303
    assert restart_calls == [None]
    assert read_value(environment, RUNTIME_SYNC_ENDPOINT_ENV) == ""
    assert read_value(environment, RUNTIME_SYNC_USERNAME_ENV) == ""
    assert read_value(environment, RUNTIME_SYNC_PASSWORD_ENV) == ""
