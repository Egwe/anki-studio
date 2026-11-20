"""Tests for login, logout, and the login requirement (AS-030)."""

import pytest
from fastapi.testclient import TestClient

from anki_studio.auth import SESSION_COOKIE, safe_next
from anki_studio.settings import StudioSettings
from tests.conftest import PASSWORD, make_client


def test_anonymous_start_page_redirects_to_login(client: TestClient) -> None:
    """The start page needs a login.

    Args:
        client: Anonymous test client.
    """
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_redirect_keeps_requested_page(client: TestClient) -> None:
    """A deep link returns to the requested page after the login.

    Args:
        client: Anonymous test client.
    """
    response = client.get("/jobs/abc?tab=karten", follow_redirects=False)

    assert response.headers["location"] == "/login?next=%2Fjobs%2Fabc%3Ftab%3Dkarten"


def test_anonymous_post_is_redirected_without_next(client: TestClient) -> None:
    """State-changing requests are never replayed after the login.

    Args:
        client: Anonymous test client.
    """
    response = client.post("/logout", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login"


def test_htmx_request_gets_401_with_redirect_header(client: TestClient) -> None:
    """Requests from htmx receive a full-page redirect instruction.

    Args:
        client: Anonymous test client.
    """
    response = client.get("/", headers={"HX-Request": "true"}, follow_redirects=False)

    assert response.status_code == 401
    assert response.headers["hx-redirect"] == "/login"


@pytest.mark.parametrize("path", ["/login", "/healthz", "/static/app.css"])
def test_public_paths_need_no_login(client: TestClient, path: str) -> None:
    """Login page, health check, and static files stay reachable.

    Args:
        client: Anonymous test client.
        path: Public path.
    """
    assert client.get(path, follow_redirects=False).status_code == 200


def test_wrong_password_is_rejected(client: TestClient) -> None:
    """A wrong password shows an error and starts no session.

    Args:
        client: Anonymous test client.
    """
    response = client.post("/login", data={"password": "falsch-geheim"}, follow_redirects=False)

    assert response.status_code == 401
    assert "Das Passwort ist falsch." in response.text
    assert client.get("/", follow_redirects=False).status_code == 303


def test_login_sets_strict_http_only_cookie(client: TestClient) -> None:
    """A correct password starts a session with a protected cookie.

    Args:
        client: Anonymous test client.
    """
    response = client.post(
        "/login", data={"password": PASSWORD, "next": "/jobs"}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/jobs"
    cookie = response.headers["set-cookie"].lower()
    assert cookie.startswith(f"{SESSION_COOKIE}=")
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert client.get("/", follow_redirects=False).status_code == 200


def test_logout_ends_session(auth_client: TestClient) -> None:
    """After logging out the start page needs a login again.

    Args:
        auth_client: Logged-in test client.
    """
    response = auth_client.post("/logout", follow_redirects=False)

    assert response.headers["location"] == "/login"
    assert auth_client.get("/", follow_redirects=False).status_code == 303


def test_logged_in_user_skips_login_page(auth_client: TestClient) -> None:
    """The login page forwards a logged-in session.

    Args:
        auth_client: Logged-in test client.
    """
    response = auth_client.get("/login?next=/jobs", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/jobs"


def test_start_page_offers_logout(auth_client: TestClient) -> None:
    """Logged-in pages show the logout button.

    Args:
        auth_client: Logged-in test client.
    """
    assert "Abmelden" in auth_client.get("/").text


def test_without_password_nobody_can_log_in(studio_settings: StudioSettings) -> None:
    """Without a configured hash the page explains the setup and login fails.

    Args:
        studio_settings: Settings of the test application.
    """
    with make_client(studio_settings, password_hash=None) as client:
        page = client.get("/login")
        response = client.post("/login", data={"password": PASSWORD}, follow_redirects=False)

    assert "anki-studio hash-password" in page.text
    assert 'type="password"' not in page.text
    assert response.status_code == 401


def test_forged_cookie_is_ignored(client: TestClient) -> None:
    """A session cookie with a wrong signature does not log in.

    Args:
        client: Anonymous test client.
    """
    client.cookies.set(SESSION_COOKIE, "eyJhdXRoZW50aWNhdGVkIjogdHJ1ZX0=.forged.signature")

    assert client.get("/", follow_redirects=False).status_code == 303


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("/jobs?tab=1", "/jobs?tab=1"),
        (None, "/"),
        ("", "/"),
        ("https://evil.example/", "/"),
        ("//evil.example/", "/"),
        ("/\\evil.example", "/"),
        ("/login", "/"),
        ("/login?next=/x", "/"),
    ],
)
def test_safe_next(target: str | None, expected: str) -> None:
    """Only local paths other than the login page are followed.

    Args:
        target: Requested continuation.
        expected: Path actually used.
    """
    assert safe_next(target) == expected
