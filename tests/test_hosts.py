"""Tests for the check of the ``Host`` header."""

import pytest
from fastapi.testclient import TestClient

from anki_studio.hosts import request_host


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("Anki-Studio.LAN:8000", "anki-studio.lan"),
        ("192.0.2.10", "192.0.2.10"),
        ("[::1]:8000", "::1"),
        ("::1", "::1"),
        ("", ""),
    ],
)
def test_request_host(header: str, expected: str) -> None:
    """The host name is lower-cased and freed from port and brackets.

    Args:
        header: Raw ``Host`` header.
        expected: Extracted host name.
    """
    scope = {"type": "http", "headers": [(b"host", header.encode())]}

    assert request_host(scope) == expected


def test_known_host_is_accepted(client: TestClient) -> None:
    """Requests to an allowed name, with any port, pass.

    Args:
        client: Test client allowing ``testserver``.
    """
    assert client.get("http://testserver:8000/healthz").status_code == 200


def test_unknown_host_is_rejected(client: TestClient) -> None:
    """Requests to another name get 400 with an explanation and headers.

    Args:
        client: Test client allowing ``testserver``.
    """
    response = client.get("http://rebinding.example/healthz")

    assert response.status_code == 400
    assert "rebinding.example" in response.text
    assert "allowed_hosts" in response.text
    assert "content-security-policy" in response.headers


def test_unknown_host_cannot_reach_static_files(client: TestClient) -> None:
    """Static files are protected by the same check.

    Args:
        client: Test client allowing ``testserver``.
    """
    assert client.get("http://evil.example/static/app.css").status_code == 400
