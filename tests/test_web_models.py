"""Tests for showing the models of a provider in the interface (AS-014)."""

import httpx
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def ollama(auth_client: TestClient) -> list[httpx.Request]:
    """Answer model list requests like an Ollama server with two models.

    Args:
        auth_client: Logged-in test client whose app uses the mock.

    Returns:
        A list receiving every request sent to the provider.
    """
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        """Record the request and list two models.

        Args:
            request: Outgoing request.

        Returns:
            An Ollama-style answer.
        """
        seen.append(request)
        return httpx.Response(
            200, json={"models": [{"name": "llama3.2:latest"}, {"name": "qwen3:8b"}]}
        )

    auth_client.app.state.http_transport = httpx.MockTransport(handle)
    return seen


def test_form_offers_model_list(auth_client: TestClient) -> None:
    """The generation form shows the model field and the load button.

    Args:
        auth_client: Logged-in test client.
    """
    page = auth_client.get("/generate").text

    assert 'x-ref="model"' in page
    assert 'hx-get="http://testserver/models"' in page
    assert "Modelle laden" in page


def test_models_of_default_profile(auth_client: TestClient, ollama: list[httpx.Request]) -> None:
    """Without a profile the default profile's provider is asked.

    Args:
        auth_client: Logged-in test client.
        ollama: Recorded provider requests.
    """
    fragment = auth_client.get("/models?profile=").text

    assert "2 Modelle von Ollama" in fragment
    assert '<option value="ollama/llama3.2:latest">' in fragment
    assert ollama[0].url.path == "/api/tags"


def test_missing_key_is_explained(auth_client: TestClient, ollama: list[httpx.Request]) -> None:
    """A provider without its key is not asked; the fragment says why.

    Args:
        auth_client: Logged-in test client.
        ollama: Recorded provider requests.
    """
    fragment = auth_client.get("/models?profile=mistral-default").text

    assert "Schlüssel fehlt: MISTRAL_API_KEY" in fragment
    assert ollama == []


def test_unknown_profile_is_explained(auth_client: TestClient) -> None:
    """An unknown profile gives a message instead of an error page.

    Args:
        auth_client: Logged-in test client.
    """
    response = auth_client.get("/models?profile=gibt-es-nicht")

    assert response.status_code == 200
    assert "gibt es nicht" in response.text


def test_key_check_view(auth_client: TestClient, ollama: list[httpx.Request]) -> None:
    """The key page variant reports that the key works and lists models.

    Args:
        auth_client: Logged-in test client.
        ollama: Recorded provider requests.
    """
    fragment = auth_client.get("/models?profile=lokal&view=keys").text

    assert "Schlüssel funktioniert: 2 Modelle von Ollama" in fragment
    assert "<code>ollama/qwen3:8b</code>" in fragment


def test_key_page_offers_check_for_stored_keys(auth_client: TestClient) -> None:
    """After storing a key the page offers to check it.

    Args:
        auth_client: Logged-in test client.
    """
    assert "Prüfen</button>" not in auth_client.get("/settings/keys").text

    auth_client.post("/settings/keys/TEST_STUDIO_KEY", data={"value": "sk-test-0123456789"})

    page = auth_client.get("/settings/keys").text
    assert "profile=nativ&amp;view=keys" in page
    assert "Prüfen</button>" in page


def test_models_need_login(client: TestClient) -> None:
    """Anonymous htmx requests are redirected to the login page.

    Args:
        client: Anonymous test client.
    """
    response = client.get("/models", headers={"HX-Request": "true"}, follow_redirects=False)

    assert response.status_code == 401
    assert response.headers["hx-redirect"] == "/login"
