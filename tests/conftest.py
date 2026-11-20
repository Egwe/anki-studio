"""Shared fixtures for the Anki Studio tests."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from anki_studio.app import create_app
from anki_studio.settings import StudioSettings


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Provide a test client for an application with default settings.

    Yields:
        A ``TestClient`` bound to a fresh application; closed afterwards.
    """
    with TestClient(create_app(StudioSettings(allowed_hosts=("testserver",)))) as test_client:
        yield test_client
