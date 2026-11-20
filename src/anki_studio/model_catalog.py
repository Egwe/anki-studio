"""Load the models a provider offers for a profile (AS-014).

Only the profile's API key goes to the provider, never document content.
Calls happen on explicit user action. The result uses LiteLLM's
``provider/model`` format, so it can be used directly as ``model``.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx
from anki_flashcards.config import ModelProfile

TIMEOUT_SECONDS = 10.0
NON_TEXT_MARKERS = (
    "embed",
    "tts",
    "whisper",
    "dall-e",
    "moderation",
    "transcribe",
    "audio",
    "realtime",
    "rerank",
)


class ModelListError(Exception):
    """Report why no model list could be loaded, without secret values."""


@dataclass(frozen=True)
class Provider:
    """Describe how to ask one provider for its models.

    Attributes:
        label: Name shown to the user.
        base: Default API base when the profile sets none.
        path: Path below the base that lists the models.
        auth: ``bearer``, ``anthropic``, ``gemini`` or ``none``.
        parser: Name of the function that reads the response.
        needs_key: Whether the default endpoint requires a key.
    """

    label: str
    base: str
    path: str
    auth: str
    parser: str
    needs_key: bool = True


PROVIDERS = {
    "openai": Provider("OpenAI", "https://api.openai.com/v1", "/models", "bearer", "data"),
    "anthropic": Provider(
        "Anthropic", "https://api.anthropic.com", "/v1/models?limit=1000", "anthropic", "data"
    ),
    "gemini": Provider(
        "Google Gemini",
        "https://generativelanguage.googleapis.com",
        "/v1beta/models?pageSize=1000",
        "gemini",
        "gemini",
    ),
    "mistral": Provider("Mistral", "https://api.mistral.ai/v1", "/models", "bearer", "data"),
    "deepseek": Provider("DeepSeek", "https://api.deepseek.com", "/models", "bearer", "data"),
    "openrouter": Provider(
        "OpenRouter", "https://openrouter.ai/api/v1", "/models", "bearer", "data", needs_key=False
    ),
    "groq": Provider("Groq", "https://api.groq.com/openai/v1", "/models", "bearer", "data"),
    "xai": Provider("xAI", "https://api.x.ai/v1", "/models", "bearer", "data"),
    "moonshot": Provider("Moonshot", "https://api.moonshot.ai/v1", "/models", "bearer", "data"),
    "ollama": Provider(
        "Ollama", "http://localhost:11434", "/api/tags", "none", "ollama", needs_key=False
    ),
    "ollama_chat": Provider(
        "Ollama", "http://localhost:11434", "/api/tags", "none", "ollama", needs_key=False
    ),
}


@dataclass(frozen=True)
class ModelList:
    """Hold the models of one profile's provider.

    Attributes:
        provider: Name shown to the user, for example ``OpenAI``.
        models: Sorted names in ``provider/model`` format.
    """

    provider: str
    models: list[str]


def provider_prefix(model: str) -> str:
    """Return the LiteLLM provider of a model name.

    Args:
        model: Name like ``openai/gpt-4o-mini``.

    Returns:
        The part before the first ``/``.
    """
    return model.split("/", 1)[0]


def list_models(
    profile: ModelProfile,
    environ: Mapping[str, str],
    transport: httpx.BaseTransport | None = None,
) -> ModelList:
    """Ask the profile's provider which models it offers.

    Args:
        profile: Profile whose provider, ``api_base`` and key are used.
        environ: Environment holding the key named by ``api_key_env``.
        transport: HTTP transport; tests pass a mock, None uses the network.

    Returns:
        The provider name and its text-generation models, sorted; models
        for embeddings, speech, images, moderation or reranking are left out.

    Raises:
        ModelListError: If the provider is unknown, a required key is
            missing, the provider cannot be reached, or it refuses the key.
    """
    prefix = provider_prefix(profile.model)
    provider = PROVIDERS.get(prefix)
    if provider is None:
        raise ModelListError(f"Für den Provider „{prefix}“ kann Anki Studio keine Liste laden.")
    key = environ.get(profile.api_key_env or "", "").strip() or None
    base = (profile.api_base or provider.base).rstrip("/")
    if key is None and provider.needs_key and base == provider.base:
        raise ModelListError(f"Schlüssel fehlt: {profile.api_key_env or 'kein api_key_env'}.")
    payload = _fetch(provider, base, key, transport)
    names = PARSERS[provider.parser](payload)
    models = sorted({f"{prefix}/{name}" for name in names if _is_text_model(name)})
    return ModelList(provider.label, models)


def _fetch(
    provider: Provider, base: str, key: str | None, transport: httpx.BaseTransport | None
) -> Any:
    """Request the model list and decode the JSON answer.

    Args:
        provider: Provider description.
        base: API base without trailing slash.
        key: API key, or None.
        transport: HTTP transport, or None for the network.

    Returns:
        The decoded JSON body.

    Raises:
        ModelListError: With a German message that never contains the key.
    """
    headers = _auth_headers(provider.auth, key)
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, transport=transport) as client:
            response = client.get(base + provider.path, headers=headers)
    except httpx.HTTPError as error:
        raise ModelListError(
            f"{provider.label} ist nicht erreichbar ({type(error).__name__})."
        ) from error
    if response.status_code in (401, 403):
        raise ModelListError(f"{provider.label} lehnt den Schlüssel ab ({response.status_code}).")
    if response.is_error:
        raise ModelListError(f"{provider.label} antwortet mit Status {response.status_code}.")
    try:
        return response.json()
    except ValueError as error:
        raise ModelListError(f"{provider.label} liefert keine lesbare Modellliste.") from error


def _auth_headers(auth: str, key: str | None) -> dict[str, str]:
    """Build the authentication headers of a provider.

    Args:
        auth: Authentication style of the provider.
        key: API key, or None.

    Returns:
        The headers; empty without key or for ``none``.
    """
    if key is None or auth == "none":
        return {}
    builders: dict[str, Callable[[str], dict[str, str]]] = {
        "bearer": lambda value: {"Authorization": f"Bearer {value}"},
        "anthropic": lambda value: {"x-api-key": value, "anthropic-version": "2023-06-01"},
        "gemini": lambda value: {"x-goog-api-key": value},
    }
    return builders[auth](key)


def _parse_data(payload: Any) -> list[str]:
    """Read OpenAI-style answers: ``{"data": [{"id": ...}]}``.

    Args:
        payload: Decoded JSON.

    Returns:
        Model identifiers.
    """
    return [str(entry["id"]) for entry in payload.get("data", []) if "id" in entry]


def _parse_gemini(payload: Any) -> list[str]:
    """Read Gemini answers and keep models that generate content.

    Args:
        payload: Decoded JSON with ``models[].name`` like ``models/gemini-2.5-flash``.

    Returns:
        Model identifiers without the ``models/`` prefix.
    """
    return [
        str(entry["name"]).removeprefix("models/")
        for entry in payload.get("models", [])
        if "generateContent" in entry.get("supportedGenerationMethods", [])
    ]


def _parse_ollama(payload: Any) -> list[str]:
    """Read Ollama answers: ``{"models": [{"name": ...}]}``.

    Args:
        payload: Decoded JSON.

    Returns:
        Installed model names, for example ``llama3.2:latest``.
    """
    return [str(entry["name"]) for entry in payload.get("models", []) if "name" in entry]


PARSERS: dict[str, Callable[[Any], list[str]]] = {
    "data": _parse_data,
    "gemini": _parse_gemini,
    "ollama": _parse_ollama,
}


def _is_text_model(name: str) -> bool:
    """Leave out models that do not generate text.

    Args:
        name: Model identifier.

    Returns:
        False for embeddings, speech, image, moderation, and reranking models.
    """
    lowered = name.lower()
    return not any(marker in lowered for marker in NON_TEXT_MARKERS)
