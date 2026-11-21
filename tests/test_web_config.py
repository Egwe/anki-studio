"""Tests for the configuration pages (AS-009, AS-016)."""

import io

import httpx
from fastapi.testclient import TestClient

from anki_studio.generator_config import load_generator_config
from anki_studio.settings import StudioSettings

PROFILE = {
    "name": "openai-4-1",
    "model": "openai/gpt-4.1",
    "api_base": "",
    "api_key_env": "OPENAI_API_KEY",
    "timeout": "120",
    "pdf_mode": "local",
    "image_input": "false",
    "options": "temperature: 0.3",
}


def config(settings: StudioSettings):
    """Load the generator configuration of the test application.

    Args:
        settings: Settings of the test application.

    Returns:
        The current ``AppConfig``.
    """
    return load_generator_config(settings.generator_path).config


def test_page_shows_effective_values_profiles_and_defaults(auth_client: TestClient) -> None:
    """The page lists effective values with source, profiles, and defaults.

    Args:
        auth_client: Logged-in test client.
    """
    page = auth_client.get("/settings/config").text

    assert "Wirksame Werte mit Herkunft" in page
    assert "<td><code>language</code></td><td>Englisch</td><td>Konfiguration</td>" in page
    assert 'id="profile-lokal"' in page and 'id="profile-anthropic-default"' in page
    assert "Auf Vorlage zurücksetzen" in page
    assert 'name="generation.language" value="Englisch"' in page


def test_create_profile_and_edit_it(
    auth_client: TestClient, studio_settings: StudioSettings
) -> None:
    """A new profile is saved and can be edited afterwards.

    Args:
        auth_client: Logged-in test client.
        studio_settings: Settings of the test application.
    """
    created = auth_client.post(
        "/settings/config/profiles/new", data=PROFILE, follow_redirects=False
    )
    form = auth_client.get("/settings/config/profiles/openai-4-1").text
    edited = auth_client.post(
        "/settings/config/profiles/openai-4-1",
        data=PROFILE | {"timeout": "60", "options": "temperature: 0.1\nmax_tokens: 2000"},
        follow_redirects=False,
    )

    assert created.headers["location"] == "/settings/config?saved=profile#profile-openai-4-1"
    assert 'value="openai/gpt-4.1"' in form and "temperature: 0.3" in form
    assert edited.status_code == 303
    profile = config(studio_settings).models["openai-4-1"]
    assert profile.timeout == 60
    assert profile.options == {"temperature": 0.1, "max_tokens": 2000}


def test_invalid_profile_shows_reasons(
    auth_client: TestClient, studio_settings: StudioSettings
) -> None:
    """Refused values are explained per field and nothing is saved.

    Args:
        auth_client: Logged-in test client.
        studio_settings: Settings of the test application.
    """
    response = auth_client.post(
        "/settings/config/profiles/new",
        data=PROFILE | {"model": "gpt", "options": "api_key: sk-geheim"},
    )

    assert response.status_code == 400
    assert "provider/modell" in response.text
    assert 'value="gpt"' in response.text
    assert "openai-4-1" not in config(studio_settings).models


def test_reset_and_delete(auth_client: TestClient, studio_settings: StudioSettings) -> None:
    """Standard profiles are reset; own profiles are deleted.

    Args:
        auth_client: Logged-in test client.
        studio_settings: Settings of the test application.
    """
    auth_client.post("/settings/config/profiles/new", data=PROFILE)
    auth_client.post(
        "/settings/config/profiles/gemini-default", data=PROFILE | {"model": "gemini/gemini-x"}
    )

    reset = auth_client.post(
        "/settings/config/profiles/gemini-default/reset", follow_redirects=False
    )
    deleted = auth_client.post(
        "/settings/config/profiles/openai-4-1/delete", follow_redirects=False
    )
    refused = auth_client.post("/settings/config/profiles/gemini-default/delete")

    assert reset.status_code == deleted.status_code == 303
    assert config(studio_settings).models["gemini-default"].model == "gemini/gemini-2.5-flash"
    assert "openai-4-1" not in config(studio_settings).models
    assert refused.status_code == 400
    assert "nur zurücksetzen" in refused.text


def test_save_defaults(auth_client: TestClient, studio_settings: StudioSettings) -> None:
    """Defaults are saved; invalid values come back with reasons.

    Args:
        auth_client: Logged-in test client.
        studio_settings: Settings of the test application.
    """
    page = auth_client.get("/settings/config").text
    assert 'name="pdf_conversion.ocr_languages" value="de en"' in page

    saved = auth_client.post(
        "/settings/config/defaults",
        data={
            "default_profile": "nativ",
            "generation.language": "Deutsch",
            "generation.limit": "25",
            "pdf_conversion.ocr_languages": "de",
            "pdf_conversion.formula_batch_size": "1",
            "pictures.backend": "none",
        },
        follow_redirects=False,
    )
    refused = auth_client.post(
        "/settings/config/defaults",
        data={"generation.chunk_size": "5", "pdf_conversion.ocr_languages": "de"},
    )

    assert saved.status_code == 303
    stored = config(studio_settings)
    assert (stored.default_profile, stored.generation.limit) == ("nativ", 25)
    assert stored.pdf_conversion.formula_batch_size == 1
    assert refused.status_code == 400
    assert "mindestens 1000" in refused.text


def test_download_and_upload(auth_client: TestClient, studio_settings: StudioSettings) -> None:
    """The YAML can be downloaded and replaced by a valid upload only.

    Args:
        auth_client: Logged-in test client.
        studio_settings: Settings of the test application.
    """
    download = auth_client.get("/settings/config/download")
    bad = auth_client.post(
        "/settings/config/upload",
        files={"file": ("x.yaml", io.BytesIO(b"models: ["), "application/yaml")},
    )
    good = auth_client.post(
        "/settings/config/upload",
        files={
            "file": (
                "x.yaml",
                io.BytesIO(b"models:\n  eins:\n    model: ollama/llama3.2\n"),
                "application/yaml",
            )
        },
        follow_redirects=False,
    )

    assert 'filename="generator.yaml"' in download.headers["content-disposition"]
    assert "models:" in download.text
    assert bad.status_code == 400 and "kein gültiges YAML" in bad.text
    assert good.status_code == 303
    assert list(config(studio_settings).models) == ["eins"]


def test_model_list_for_unsaved_profile(auth_client: TestClient) -> None:
    """The profile editor can list models before the profile is saved.

    Args:
        auth_client: Logged-in test client.
    """
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        """Record the request and list one model.

        Args:
            request: Outgoing request.

        Returns:
            An Ollama-style answer.
        """
        seen.append(request)
        return httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]})

    auth_client.app.state.http_transport = httpx.MockTransport(handle)

    fragment = auth_client.get(
        "/models",
        params={"model": "ollama_chat/x", "api_base": "http://ollama.lan:11434", "api_key_env": ""},
    ).text
    invalid = auth_client.get("/models", params={"model": "kein-provider"}).text

    assert "ollama_chat/qwen3:8b" in fragment
    assert str(seen[0].url) == "http://ollama.lan:11434/api/tags"
    assert "provider/modell" in invalid


def test_config_needs_login(client: TestClient) -> None:
    """Anonymous requests cannot read or change the configuration.

    Args:
        client: Anonymous test client.
    """
    assert client.get("/settings/config/download", follow_redirects=False).status_code == 303
    assert (
        client.post(
            "/settings/config/profiles/new", data=PROFILE, follow_redirects=False
        ).status_code
        == 303
    )
