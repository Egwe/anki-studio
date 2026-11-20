"""Tests for the application factory, layout, static files, and headers."""

import re
from importlib.metadata import version

import pytest
from fastapi.testclient import TestClient

from anki_studio.headers import CONTENT_SECURITY_POLICY

VENDOR_FILES = (
    ("vendor/htmx-2.0.11.min.js", "javascript"),
    ("vendor/htmx-ext-sse-2.2.4.min.js", "javascript"),
    ("vendor/alpinejs-3.17.5.min.js", "javascript"),
    ("vendor/pico-2.1.1.min.css", "text/css"),
    ("app.css", "text/css"),
    ("favicon.svg", "image/svg+xml"),
)


def test_start_page_shows_component_versions(client: TestClient) -> None:
    """The start page renders and names the installed versions.

    Args:
        client: Test client of a default application.
    """
    response = client.get("/")

    assert response.status_code == 200
    assert "Anki Studio" in response.text
    assert version("anki") in response.text
    assert version("anki-flashcard-generator") in response.text


def test_health_check(client: TestClient) -> None:
    """The health check answers with a fixed JSON body.

    Args:
        client: Test client of a default application.
    """
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(("path", "content_type"), VENDOR_FILES)
def test_static_files_are_served(client: TestClient, path: str, content_type: str) -> None:
    """Bundled frontend files are served by the application itself.

    Args:
        client: Test client of a default application.
        path: File below ``/static``.
        content_type: Expected part of the content type.
    """
    response = client.get(f"/static/{path}")

    assert response.status_code == 200
    assert content_type in response.headers["content-type"]


def test_page_loads_only_local_resources(client: TestClient) -> None:
    """Every script, stylesheet, and icon of the layout comes from the app.

    Args:
        client: Test client of a default application.
    """
    html = client.get("/").text
    references = re.findall(r'(?:src|href)="([^"]+)"', html)

    assert references
    for reference in references:
        assert reference.startswith(("/", "http://testserver/")), reference


@pytest.mark.parametrize("path", ["/", "/static/app.css", "/healthz"])
def test_security_headers(client: TestClient, path: str) -> None:
    """HTML, static files, and JSON carry the security headers.

    Args:
        client: Test client of a default application.
        path: Requested path.
    """
    headers = client.get(path).headers

    assert headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["referrer-policy"] == "no-referrer"


def test_policy_forbids_external_sources() -> None:
    """The policy allows only the app itself as source of resources."""
    directives = dict(item.split(" ", 1) for item in CONTENT_SECURITY_POLICY.split("; "))

    assert directives["default-src"] == "'self'"
    assert directives["style-src"] == "'self'"
    assert "unsafe-inline" not in CONTENT_SECURITY_POLICY


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_documentation_is_disabled(client: TestClient, path: str) -> None:
    """The interactive API documentation, which would load a CDN, is off.

    Args:
        client: Test client of a default application.
        path: Default documentation path of FastAPI.
    """
    assert client.get(path).status_code == 404
