"""Tests for loading the model list of a provider (AS-014)."""

import httpx
import pytest
from anki_flashcards.config import ModelProfile

from anki_studio.model_catalog import ModelListError, list_models

KEY = "sk-test-geheim-0123456789"


def profile(model: str, api_key_env: str | None = "TEST_KEY", api_base: str | None = None):
    """Build a model profile for the tests.

    Args:
        model: ``provider/model`` name.
        api_key_env: Variable holding the key.
        api_base: Optional endpoint.

    Returns:
        A validated profile.
    """
    return ModelProfile(model=model, api_key_env=api_key_env, api_base=api_base)


def responder(status: int, body: object, seen: list[httpx.Request]) -> httpx.MockTransport:
    """Build a transport that records requests and returns a fixed answer.

    Args:
        status: HTTP status of the answer.
        body: JSON body of the answer.
        seen: List receiving every request.

    Returns:
        A mock transport.
    """

    def handle(request: httpx.Request) -> httpx.Response:
        """Record the request and answer.

        Args:
            request: Outgoing request.

        Returns:
            The fixed response.
        """
        seen.append(request)
        return httpx.Response(status, json=body)

    return httpx.MockTransport(handle)


def test_openai_models_with_bearer_key() -> None:
    """OpenAI lists via /models with a bearer key; non-text models are dropped."""
    seen: list[httpx.Request] = []
    body = {"data": [{"id": "gpt-4o-mini"}, {"id": "text-embedding-3-small"}, {"id": "gpt-4.1"}]}

    result = list_models(
        profile("openai/gpt-4o-mini"), {"TEST_KEY": KEY}, responder(200, body, seen)
    )

    assert result.provider == "OpenAI"
    assert result.models == ["openai/gpt-4.1", "openai/gpt-4o-mini"]
    assert str(seen[0].url) == "https://api.openai.com/v1/models"
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"


def test_anthropic_uses_its_headers() -> None:
    """Anthropic needs x-api-key and anthropic-version."""
    seen: list[httpx.Request] = []
    body = {"data": [{"id": "claude-sonnet-4-5"}]}

    result = list_models(
        profile("anthropic/claude-sonnet-4-5", api_base="https://api.anthropic.com/"),
        {"TEST_KEY": KEY},
        responder(200, body, seen),
    )

    assert result.models == ["anthropic/claude-sonnet-4-5"]
    assert seen[0].url.path == "/v1/models"
    assert seen[0].headers["x-api-key"] == KEY
    assert seen[0].headers["anthropic-version"] == "2023-06-01"


def test_gemini_keeps_generating_models_and_hides_key_from_url() -> None:
    """Gemini gets the key as header and only content-generating models remain."""
    seen: list[httpx.Request] = []
    body = {
        "models": [
            {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
        ]
    }

    result = list_models(
        profile("gemini/gemini-2.5-flash"), {"TEST_KEY": KEY}, responder(200, body, seen)
    )

    assert result.models == ["gemini/gemini-2.5-flash"]
    assert KEY not in str(seen[0].url)
    assert seen[0].headers["x-goog-api-key"] == KEY


def test_ollama_lists_installed_models_without_key() -> None:
    """Ollama needs no key and keeps the profile's prefix."""
    seen: list[httpx.Request] = []
    body = {"models": [{"name": "llama3.2:latest"}, {"name": "qwen2.5vl:7b"}]}

    result = list_models(
        profile("ollama_chat/llama3.2", api_key_env=None, api_base="http://ollama.lan:11434"),
        {},
        responder(200, body, seen),
    )

    assert result.models == ["ollama_chat/llama3.2:latest", "ollama_chat/qwen2.5vl:7b"]
    assert str(seen[0].url) == "http://ollama.lan:11434/api/tags"
    assert "authorization" not in seen[0].headers


def test_openrouter_keeps_nested_names() -> None:
    """OpenRouter model ids keep their own provider part."""
    body = {"data": [{"id": "openai/gpt-4o-mini"}]}

    result = list_models(profile("openrouter/openai/gpt-4o-mini"), {}, responder(200, body, []))

    assert result.models == ["openrouter/openai/gpt-4o-mini"]


def test_custom_server_works_without_key() -> None:
    """An OpenAI-compatible server with its own base may run without key."""
    seen: list[httpx.Request] = []

    result = list_models(
        profile(
            "openai/mein-modell", api_key_env="CUSTOM_LLM_API_KEY", api_base="http://vllm:8000/v1"
        ),
        {},
        responder(200, {"data": [{"id": "mein-modell"}]}, seen),
    )

    assert result.models == ["openai/mein-modell"]
    assert str(seen[0].url) == "http://vllm:8000/v1/models"


@pytest.mark.parametrize(
    ("status", "message"),
    [(401, "lehnt den Schlüssel ab"), (403, "lehnt den Schlüssel ab"), (500, "Status 500")],
)
def test_error_answers_are_explained(status: int, message: str) -> None:
    """Refused keys and server errors give a message without the key.

    Args:
        status: HTTP status of the answer.
        message: Expected part of the message.
    """
    with pytest.raises(ModelListError, match=message) as error:
        list_models(profile("openai/gpt-4o-mini"), {"TEST_KEY": KEY}, responder(status, {}, []))

    assert KEY not in str(error.value)


def test_unreachable_provider_is_explained() -> None:
    """Connection problems become a readable message."""

    def fail(request: httpx.Request) -> httpx.Response:
        """Simulate a refused connection.

        Args:
            request: Outgoing request.

        Raises:
            httpx.ConnectError: Always.
        """
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(ModelListError, match="nicht erreichbar"):
        list_models(profile("openai/gpt-4o-mini"), {"TEST_KEY": KEY}, httpx.MockTransport(fail))


def test_missing_key_is_reported_before_any_request() -> None:
    """Providers that need a key are not asked without one."""
    seen: list[httpx.Request] = []

    with pytest.raises(ModelListError, match="Schlüssel fehlt: TEST_KEY"):
        list_models(profile("mistral/mistral-small-latest"), {}, responder(200, {}, seen))

    assert seen == []


def test_unknown_provider_is_reported() -> None:
    """Providers without a known list endpoint are named."""
    with pytest.raises(ModelListError, match="cohere"):
        list_models(profile("cohere/command-r"), {"TEST_KEY": KEY}, responder(200, {}, []))
