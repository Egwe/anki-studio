"""Tests for changing the generator YAML through the interface (AS-009)."""

from pathlib import Path

import pytest
from anki_flashcards.config import PDFMode, PictureBackend

from anki_studio.config_editor import (
    ConfigEditError,
    delete_profile,
    replace_config,
    reset_profile,
    save_defaults,
    save_profile,
)
from anki_studio.generator_config import (
    ensure_generator_config,
    load_generator_config,
    template_config,
)

PROFILE = {
    "model": "openai/gpt-4.1",
    "api_base": "https://api.openai.com/v1",
    "api_key_env": "OPENAI_API_KEY",
    "timeout": "120",
    "pdf_mode": "local",
    "image_input": "false",
    "options": "temperature: 0.3\nmax_tokens: 4096",
}


@pytest.fixture
def path(tmp_path: Path) -> Path:
    """Create a generator YAML from the template.

    Args:
        tmp_path: Temporary test folder.

    Returns:
        Path of the generator YAML.
    """
    target = tmp_path / "generator.yaml"
    ensure_generator_config(target, tmp_path / "models")
    return target


def test_create_and_edit_profile(path: Path) -> None:
    """A new profile is validated and saved; editing replaces its values.

    Args:
        path: Generator YAML.
    """
    save_profile(path, "openai-4-1", PROFILE, new=True)
    save_profile(path, "openai-4-1", PROFILE | {"timeout": "60", "options": ""}, new=False)

    profile = load_generator_config(path).config.models["openai-4-1"]
    assert (profile.model, profile.timeout, profile.options) == ("openai/gpt-4.1", 60, {})


@pytest.mark.parametrize(
    ("name", "fields", "field", "message"),
    [
        ("Neu!", PROFILE, "name", "Kleinbuchstaben"),
        ("cli", PROFILE, "name", "cli"),
        ("ollama-local", PROFILE, "name", "gibt es schon"),
        ("neu", PROFILE | {"model": "gpt"}, "model", "provider/modell"),
        ("neu", PROFILE | {"timeout": "0"}, "timeout", "mindestens 1"),
        ("neu", PROFILE | {"api_key_env": "sk-abc def"}, "api_key_env", "environment variable"),
        ("neu", PROFILE | {"options": "api_key: sk-123"}, "options", "reserved"),
        ("neu", PROFILE | {"options": "- a\n- b"}, "options", "name: wert"),
        ("neu", PROFILE | {"pdf_mode": "magic"}, "pdf_mode", "Erlaubt"),
    ],
)
def test_invalid_profiles_are_refused(
    path: Path, name: str, fields: dict[str, str], field: str, message: str
) -> None:
    """Bad names and values are refused per field; the file stays unchanged.

    Args:
        path: Generator YAML.
        name: Profile name.
        fields: Entered values.
        field: Expected field of the message.
        message: Expected part of the message.
    """
    before = path.read_text(encoding="utf-8")

    with pytest.raises(ConfigEditError) as error:
        save_profile(path, name, fields, new=True)

    assert message in error.value.errors[field]
    assert path.read_text(encoding="utf-8") == before


def test_standard_profiles_can_be_reset_but_not_deleted(path: Path, tmp_path: Path) -> None:
    """Standard profiles return to the template; deleting them is refused.

    Args:
        path: Generator YAML.
        tmp_path: Temporary test folder.
    """
    template = template_config(tmp_path / "models")
    save_profile(path, "gemini-default", PROFILE | {"model": "gemini/gemini-x"}, new=False)

    with pytest.raises(ConfigEditError, match="nur zurücksetzen"):
        delete_profile(path, "gemini-default", set(template.models))
    reset_profile(path, "gemini-default", template)

    assert (
        load_generator_config(path).config.models["gemini-default"].model
        == "gemini/gemini-2.5-flash"
    )


def test_own_profiles_can_be_deleted_unless_in_use(path: Path, tmp_path: Path) -> None:
    """Deleting works for own profiles that are not referenced.

    Args:
        path: Generator YAML.
        tmp_path: Temporary test folder.
    """
    standard = set(template_config(tmp_path / "models").models)
    save_profile(path, "eigen", PROFILE, new=True)
    save_defaults(path, {"default_profile": "eigen", "pdf_conversion.ocr_languages": "de en"})

    with pytest.raises(ConfigEditError) as error:
        delete_profile(path, "eigen", standard)
    save_defaults(path, {"default_profile": "ollama-local", "pdf_conversion.ocr_languages": "de"})
    delete_profile(path, "eigen", standard)

    assert "Unknown model profile" in error.value.errors["form"]
    assert "eigen" not in load_generator_config(path).config.models


def test_save_defaults(path: Path) -> None:
    """Default profile, generation and conversion values are saved together.

    Args:
        path: Generator YAML.
    """
    save_defaults(
        path,
        {
            "default_profile": "openai-default",
            "generation.limit": "0",
            "generation.language": "Englisch",
            "generation.instructions": "Kurze Antworten.",
            "generation.pdf_mode": "native",
            "generation.subdecks": "true",
            "pdf_conversion.ocr_languages": "de, en",
            "pdf_conversion.formulas": "true",
            "pdf_conversion.formula_batch_size": "1",
            "pictures.backend": "none",
        },
    )

    config = load_generator_config(path).config
    assert config.default_profile == "openai-default"
    assert (config.generation.limit, config.generation.language) == (0, "Englisch")
    assert config.generation.pdf_mode is PDFMode.NATIVE
    assert config.generation.subdecks
    assert config.pdf_conversion.ocr_languages == ["de", "en"]
    assert config.pdf_conversion.formula_batch_size == 1
    assert config.pdf_conversion.pictures.backend is PictureBackend.NONE
    assert "anthropic-default" in config.models


@pytest.mark.parametrize(
    ("fields", "field"),
    [
        ({"generation.chunk_size": "10"}, "generation.chunk_size"),
        ({"pdf_conversion.formula_batch_size": "0"}, "pdf_conversion.formula_batch_size"),
        ({"default_profile": "gibt-es-nicht"}, "form"),
    ],
)
def test_invalid_defaults_are_refused(path: Path, fields: dict[str, str], field: str) -> None:
    """Out-of-range defaults and unknown profiles are refused per field.

    Args:
        path: Generator YAML.
        fields: Entered values.
        field: Expected field of the message.
    """
    with pytest.raises(ConfigEditError) as error:
        save_defaults(path, {"pdf_conversion.ocr_languages": "de"} | fields)

    assert field in error.value.errors


def test_replace_config_validates_upload(path: Path) -> None:
    """An uploaded file replaces the configuration only if it is valid.

    Args:
        path: Generator YAML.
    """
    with pytest.raises(ConfigEditError, match="kein gültiges YAML"):
        replace_config(path, "models: [")
    with pytest.raises(ConfigEditError):
        replace_config(path, "models:\n  x:\n    model: kein-provider\n")

    replace_config(path, "default_profile: eins\nmodels:\n  eins:\n    model: ollama/llama3.2\n")

    assert list(load_generator_config(path).config.models) == ["eins"]
