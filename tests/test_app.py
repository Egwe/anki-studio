"""Tests for the application factory, layout, static files, and headers."""

import re
from importlib.metadata import version
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from anki_studio.generator_config import load_generator_config
from anki_studio.headers import CONTENT_SECURITY_POLICY
from anki_studio.settings import StudioSettings
from tests.conftest import make_client

VENDOR_FILES = (
    ("vendor/htmx-2.0.11.min.js", "javascript"),
    ("vendor/htmx-ext-sse-2.2.4.min.js", "javascript"),
    ("vendor/alpinejs-3.17.5.min.js", "javascript"),
    ("vendor/pico-2.1.1.min.css", "text/css"),
    ("app.css", "text/css"),
    ("favicon.svg", "image/svg+xml"),
)


def test_start_page_shows_component_versions(auth_client: TestClient) -> None:
    """The start page renders and names the installed versions.

    Args:
        auth_client: Logged-in test client.
    """
    response = auth_client.get("/")

    assert response.status_code == 200
    assert "Anki Studio" in response.text
    assert version("anki") in response.text
    assert version("anki-flashcard-generator") in response.text


def test_start_page_names_available_workflows(auth_client: TestClient) -> None:
    """The start page points to workflows that are already available.

    Args:
        auth_client: Logged-in test client.
    """
    response = auth_client.get("/")

    assert "Karten prüfen und schreiben" in response.text
    assert "folgen in den nächsten Ausbaustufen" not in response.text


def test_health_check(client: TestClient) -> None:
    """The health check answers with a fixed JSON body.

    Args:
        client: Anonymous test client.
    """
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(("path", "content_type"), VENDOR_FILES)
def test_static_files_are_served(client: TestClient, path: str, content_type: str) -> None:
    """Bundled frontend files are served by the application itself.

    Args:
        client: Anonymous test client.
        path: File below ``/static``.
        content_type: Expected part of the content type.
    """
    response = client.get(f"/static/{path}")

    assert response.status_code == 200
    assert content_type in response.headers["content-type"]


def assert_local_references(html: str) -> None:
    """Check that every script, stylesheet, icon, and form target is local.

    Args:
        html: Rendered page.
    """
    references = re.findall(r'(?:src|href|action)="([^"]+)"', html)

    assert references
    for reference in references:
        assert reference.startswith(("/", "http://testserver/")), reference


def test_login_page_loads_only_local_resources(client: TestClient) -> None:
    """The login page references only resources of the app.

    Args:
        client: Anonymous test client.
    """
    assert_local_references(client.get("/login").text)


def test_start_page_loads_only_local_resources(auth_client: TestClient) -> None:
    """The start page, including the logout form, references only the app.

    Args:
        auth_client: Logged-in test client.
    """
    assert_local_references(auth_client.get("/").text)


@pytest.mark.parametrize("path", ["/", "/login", "/static/app.css", "/healthz"])
def test_security_headers(client: TestClient, path: str) -> None:
    """HTML, static files, and JSON carry the security headers.

    Args:
        client: Anonymous test client.
        path: Requested path.
    """
    headers = client.get(path, follow_redirects=False).headers

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
def test_api_documentation_is_disabled(auth_client: TestClient, path: str) -> None:
    """The interactive API documentation, which would load a CDN, is off.

    Args:
        auth_client: Logged-in test client.
        path: Default documentation path of FastAPI.
    """
    assert auth_client.get(path).status_code == 404


def test_start_creates_generator_config_in_data_dir(tmp_path: Path) -> None:
    """Without a configured path the app writes generator.yaml with all providers.

    Args:
        tmp_path: Temporary test folder.
    """
    settings = StudioSettings(allowed_hosts=("testserver",), data_dir=tmp_path / "data")

    with make_client(settings) as client:
        page = client.get("/healthz")

    assert page.status_code == 200
    created = load_generator_config(tmp_path / "data" / "generator.yaml").config
    assert "anthropic-default" in created.models
    assert created.pdf_conversion.models_dir == tmp_path / "data" / "models"
