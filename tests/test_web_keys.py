"""Tests for entering API keys in the interface (AS-035)."""

import logging
import os

import pytest
from fastapi.testclient import TestClient

from anki_studio.secret_store import STORE_FILE
from anki_studio.settings import StudioSettings
from tests.conftest import PASSWORD, make_client

VALUE = "sk-test-geheim-0123456789"


def store_key(client: TestClient, name: str, value: str = VALUE):
    """Submit a key without following the redirect.

    Args:
        client: Logged-in test client.
        name: Variable to set.
        value: Key value.

    Returns:
        The response.
    """
    return client.post(f"/settings/keys/{name}", data={"value": value}, follow_redirects=False)


def test_page_lists_variables_of_all_profiles(auth_client: TestClient) -> None:
    """Every key variable of the profiles appears with the using profiles.

    Args:
        auth_client: Logged-in test client.
    """
    page = auth_client.get("/settings/keys").text

    assert "TEST_STUDIO_KEY" in page
    assert "Profile: nativ" in page
    assert "OPENAI_API_KEY" in page
    assert "Profile: openai-default, openai-native-pdf" in page


def test_stored_key_is_never_shown(
    auth_client: TestClient, studio_settings: StudioSettings, caplog: pytest.LogCaptureFixture
) -> None:
    """Saving shows only the status; the value stays out of pages, logs, and disk.

    Args:
        auth_client: Logged-in test client.
        studio_settings: Settings of the test application.
        caplog: Pytest fixture capturing log records.
    """
    caplog.set_level(logging.INFO)

    response = store_key(auth_client, "TEST_STUDIO_KEY")

    assert response.status_code == 303
    assert response.headers["location"].startswith("/settings/keys?saved=TEST_STUDIO_KEY")
    page = auth_client.get(response.headers["location"]).text
    assert "Schlüssel TEST_STUDIO_KEY gespeichert." in page
    assert VALUE not in page
    assert "TEST_STUDIO_KEY gespeichert" in caplog.text
    assert VALUE not in caplog.text
    assert VALUE.encode() not in (studio_settings.data_dir / STORE_FILE).read_bytes()
    assert os.environ["TEST_STUDIO_KEY"] == VALUE


def test_stored_key_is_used_by_profiles(auth_client: TestClient) -> None:
    """After saving, the generation form no longer reports a missing key.

    Args:
        auth_client: Logged-in test client.
    """
    line = "nativ – openai/gpt-4o-mini (native, Schlüssel fehlt)"
    assert line in auth_client.get("/generate").text

    store_key(auth_client, "TEST_STUDIO_KEY")

    assert line not in auth_client.get("/generate").text
    assert "nativ – openai/gpt-4o-mini (native)" in auth_client.get("/generate").text


def test_key_survives_restart(studio_settings: StudioSettings) -> None:
    """A new application with the same encryption key applies stored keys.

    Args:
        studio_settings: Settings of the test application.
    """
    with make_client(studio_settings) as client:
        client.post("/login", data={"password": PASSWORD})
        store_key(client, "TEST_STUDIO_KEY")
    os.environ.pop("TEST_STUDIO_KEY")

    with make_client(studio_settings):
        assert os.environ["TEST_STUDIO_KEY"] == VALUE


def test_delete_removes_key(auth_client: TestClient) -> None:
    """Deleting a stored key brings back the missing status.

    Args:
        auth_client: Logged-in test client.
    """
    store_key(auth_client, "TEST_STUDIO_KEY")

    response = auth_client.post("/settings/keys/TEST_STUDIO_KEY/delete", follow_redirects=False)

    assert "deleted=TEST_STUDIO_KEY" in response.headers["location"]
    assert "TEST_STUDIO_KEY" not in os.environ


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("PATH", VALUE, "kein erlaubter Name"),
        ("LD_PRELOAD", VALUE, "kein erlaubter Name"),
        ("TEST_STUDIO_KEY", "  ", "Bitte einen Schlüssel"),
        ("TEST_STUDIO_KEY", "sk-a\nb", "Zeilenumbrüche"),
    ],
)
def test_invalid_input_is_refused(
    auth_client: TestClient, name: str, value: str, message: str
) -> None:
    """Disallowed names and bad values are refused without effect.

    Args:
        auth_client: Logged-in test client.
        name: Variable to set.
        value: Submitted value.
        message: Expected part of the message.
    """
    before = os.environ.get(name)

    response = store_key(auth_client, name, value)

    assert response.status_code == 400
    assert message in response.text
    assert os.environ.get(name) == before


def test_environment_file_values_are_read_only(
    studio_settings: StudioSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keys from the environment file are shown as such and cannot be changed.

    Args:
        studio_settings: Settings of the test application.
        monkeypatch: Pytest fixture for environment changes.
    """
    monkeypatch.setenv("TEST_STUDIO_KEY", "aus-der-env-datei")
    with make_client(studio_settings) as client:
        client.post("/login", data={"password": PASSWORD})
        page = client.get("/settings/keys").text
        response = store_key(client, "TEST_STUDIO_KEY")

    assert "aus der Umgebungsdatei" in page
    assert "aus-der-env-datei" not in page
    assert response.status_code == 400
    assert os.environ["TEST_STUDIO_KEY"] == "aus-der-env-datei"


def test_without_encryption_key_nothing_is_stored(studio_settings: StudioSettings) -> None:
    """Without ANKI_STUDIO_SECRET_KEY the page explains it and refuses saving.

    Args:
        studio_settings: Settings of the test application.
    """
    with make_client(studio_settings, secret_key=None) as client:
        client.post("/login", data={"password": PASSWORD})
        page = client.get("/settings/keys").text
        response = store_key(client, "TEST_STUDIO_KEY")

    assert "ANKI_STUDIO_SECRET_KEY" in page
    assert response.status_code == 400
    assert not (studio_settings.data_dir / STORE_FILE).exists()


def test_keys_need_login(client: TestClient) -> None:
    """Anonymous requests cannot read or change keys.

    Args:
        client: Anonymous test client.
    """
    assert client.get("/settings/keys", follow_redirects=False).status_code == 303
    assert store_key(client, "TEST_STUDIO_KEY").headers["location"] == "/login"
    assert "TEST_STUDIO_KEY" not in os.environ
