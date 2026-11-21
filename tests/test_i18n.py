"""Tests for the session-based interface language selection."""

from fastapi.testclient import TestClient

from tests.conftest import PASSWORD


def test_new_sessions_render_english_by_default(client: TestClient) -> None:
    """Render the public login form in English without a selected locale.

    Args:
        client: Anonymous application client with a new signed session.
    """
    response = client.get("/login")

    assert response.status_code == 200
    assert '<html lang="en">' in response.text
    assert "Log in" in response.text
    assert "Anmelden" not in response.text


def test_language_selection_preserves_german_through_login(client: TestClient) -> None:
    """Keep a public German language choice after the login session is renewed.

    Args:
        client: Anonymous application client with test credentials.
    """
    selection = client.post(
        "/language", data={"locale": "de", "next": "/login"}, follow_redirects=False
    )
    assert selection.status_code == 303
    assert selection.headers["location"] == "/login"

    login_page = client.get("/login")
    assert '<html lang="de">' in login_page.text
    assert "Anmelden" in login_page.text

    login = client.post("/login", data={"password": PASSWORD}, follow_redirects=False)
    assert login.status_code == 303

    start_page = client.get("/")
    assert '<html lang="de">' in start_page.text
    assert "Karten generieren" in start_page.text


def test_language_route_rejects_external_return_location(client: TestClient) -> None:
    """Refuse an external target even though language selection is public.

    Args:
        client: Anonymous application client.
    """
    response = client.post(
        "/language",
        data={"locale": "en", "next": "https://outside.example/"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/"
