"""Tests for validating the generation form (AS-001)."""

import pytest
from anki_flashcards.config import PDFMode, PictureBackend
from pydantic import ValidationError

from anki_studio.forms import GenerateForm, Target, form_errors


def errors_for(values: dict[str, str]) -> dict[str, str]:
    """Validate raw form values and return the German messages.

    Args:
        values: Raw form values as strings.

    Returns:
        Field name to message.
    """
    with pytest.raises(ValidationError) as error:
        GenerateForm.model_validate(values)
    return form_errors(error.value.errors())


def test_empty_form_sets_nothing() -> None:
    """Blank fields are left to the YAML configuration."""
    form = GenerateForm.model_validate(
        {"deck": " ", "limit": "", "pdf_mode": "", "subdecks": "", "model": ""}
    )

    assert form.target is Target.NEW_APKG
    assert form.generator_values() == {}


def test_values_are_typed_for_the_generator() -> None:
    """Numbers become ints, modes become enum objects, switches stay explicit."""
    form = GenerateForm.model_validate(
        {
            "deck": " Vorlesung :: Kapitel 1 ",
            "profile": "lokal",
            "limit": "0",
            "chunk_size": "1000",
            "timeout": "3600",
            "pdf_mode": "structured",
            "picture_backend": "none",
            "subdecks": "true",
            "formulas": "false",
            "instructions": "Kurze Antworten.",
        }
    )

    values = form.generator_values()

    assert values == {
        "deck": "Vorlesung::Kapitel 1",
        "profile": "lokal",
        "limit": 0,
        "chunk_size": 1000,
        "timeout": 3600,
        "pdf_mode": PDFMode.STRUCTURED,
        "picture_backend": PictureBackend.NONE,
        "subdecks": True,
        "formulas": False,
        "instructions": "Kurze Antworten.",
    }
    assert type(values["pdf_mode"]) is PDFMode


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("limit", "-1", "mindestens 0"),
        ("chunk_size", "999", "mindestens 1000"),
        ("chunk_size", "100001", "höchstens 100000"),
        ("timeout", "0", "mindestens 1"),
        ("timeout", "3601", "höchstens 3600"),
        ("limit", "zehn", "ganze Zahl"),
        ("pdf_mode", "magic", "Erlaubt"),
        ("picture_backend", "cloud", "Erlaubt"),
        ("model", "llama3", "provider/modell"),
        ("deck", "A::::B", "leerer Ebene"),
        ("instructions", "x" * 5001, "5000 Zeichen"),
    ],
)
def test_invalid_values_get_german_messages(field: str, value: str, message: str) -> None:
    """Out-of-range or malformed values are reported per field.

    Args:
        field: Form field.
        value: Invalid raw value.
        message: Expected part of the message.
    """
    assert message in errors_for({field: value})[field]


def test_target_and_confirmation() -> None:
    """The target and the transfer confirmation are read from the form."""
    form = GenerateForm.model_validate({"target": "extend_apkg", "confirm_transfer": "on"})

    assert form.target is Target.EXTEND_APKG
    assert form.confirm_transfer
    assert "target" not in form.generator_values()


def test_unknown_target_is_rejected() -> None:
    """Only the defined targets are accepted."""
    assert "Erlaubt" in errors_for({"target": "sammlung"})["target"]
