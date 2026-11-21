"""Validate the generation form before anything reaches the generator (AS-001).

The generator does not check types or ranges itself: enums must be enum
objects, and limit, chunk size, and timeout must be within their bounds.
Empty fields are left out so the YAML configuration decides; yes/no
options are only passed when the form sent them.
"""

from enum import StrEnum
from typing import Annotated, Any

from anki_flashcards.config import PDFMode, PictureBackend
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator

TEXT_FIELDS = (
    "deck",
    "profile",
    "model",
    "api_base",
    "language",
    "instructions",
    "picture_profile",
)
VALUE_FIELDS = ("timeout", "limit", "chunk_size", "pdf_mode", "picture_backend")
SWITCH_FIELDS = ("subdecks", "formulas", "force_ocr", "allow_unreadable", "allow_cpu")
MESSAGES = {
    "greater_than_equal": "Wert muss mindestens {ge} sein.",
    "less_than_equal": "Wert muss höchstens {le} sein.",
    "int_parsing": "Bitte eine ganze Zahl eingeben.",
    "int_from_float": "Bitte eine ganze Zahl eingeben.",
    "bool_parsing": "Bitte ja oder nein wählen.",
    "string_too_long": "Höchstens {max_length} Zeichen.",
    "string_pattern_mismatch": "Format provider/modell, zum Beispiel ollama/llama3.2.",
    "enum": "Erlaubt: {expected}.",
    "value_error": "{error}",
}

ENGLISH_MESSAGES = {
    "greater_than_equal": "Value must be at least {ge}.",
    "less_than_equal": "Value must be at most {le}.",
    "int_parsing": "Enter a whole number.",
    "int_from_float": "Enter a whole number.",
    "bool_parsing": "Choose yes or no.",
    "string_too_long": "At most {max_length} characters.",
    "string_pattern_mismatch": "Use provider/model format, for example ollama/llama3.2.",
    "enum": "Allowed: {expected}.",
    "value_error": "{error}",
}


class Target(StrEnum):
    """Name where the reviewed cards go."""

    NEW_APKG = "new_apkg"
    EXTEND_APKG = "extend_apkg"
    COLLECTION = "collection"


class ExportTarget(StrEnum):
    """Name where an uploaded card JSON is exported."""

    NEW_APKG = "new_apkg"
    COLLECTION = "collection"


def _blank_to_none(value: Any) -> Any:
    """Treat an empty or whitespace-only form value as not set.

    Args:
        value: Raw form value.

    Returns:
        None for blank strings, otherwise the value unchanged.
    """
    if isinstance(value, str) and not value.strip():
        return None
    return value


Optional = BeforeValidator(_blank_to_none)


class GenerateForm(BaseModel):
    """Hold the validated fields of the generation form.

    Attributes:
        target: New APKG, extension of an uploaded APKG, or local synced
            collection.
        deck: Target deck, ``::`` for subdecks; empty uses YAML or file name.
        profile: Model profile name; empty uses the YAML default.
        model: ``provider/model``; empty uses the profile.
        api_base: Endpoint of the provider; empty uses the profile.
        timeout: Seconds per request, 1–3600, or None.
        language: Card language; empty uses YAML.
        limit: Maximum cards, 0 for unlimited, or None.
        instructions: Additional instructions; empty uses YAML.
        chunk_size: Characters per request, 1000–100000, or None.
        pdf_mode: PDF processing mode, or None.
        subdecks: AI assigns subdecks; None leaves the YAML value.
        formulas: Structured mode reads formulas; None leaves YAML.
        force_ocr: Structured mode reads every page with OCR; None leaves YAML.
        allow_unreadable: Placeholders instead of aborting; None leaves YAML.
        allow_cpu: Structured mode without GPU; None leaves YAML.
        picture_backend: Picture description backend, or None.
        picture_profile: Profile describing pictures; empty uses YAML.
        confirm_transfer: The user confirmed that content goes to a provider.
    """

    model_config = ConfigDict(str_strip_whitespace=True, frozen=True)

    target: Target = Target.NEW_APKG
    deck: str = Field(default="", max_length=200)
    profile: str = Field(default="", max_length=100)
    model: str = Field(default="", max_length=200, pattern=r"^$|^[^/\s]+/\S+$")
    api_base: str = Field(default="", max_length=500)
    timeout: Annotated[int | None, Optional] = Field(default=None, ge=1, le=3600)
    language: str = Field(default="", max_length=50)
    limit: Annotated[int | None, Optional] = Field(default=None, ge=0)
    instructions: str = Field(default="", max_length=5000)
    chunk_size: Annotated[int | None, Optional] = Field(default=None, ge=1000, le=100_000)
    pdf_mode: Annotated[PDFMode | None, Optional] = None
    subdecks: Annotated[bool | None, Optional] = None
    formulas: Annotated[bool | None, Optional] = None
    force_ocr: Annotated[bool | None, Optional] = None
    allow_unreadable: Annotated[bool | None, Optional] = None
    allow_cpu: Annotated[bool | None, Optional] = None
    picture_backend: Annotated[PictureBackend | None, Optional] = None
    picture_profile: str = Field(default="", max_length=100)
    confirm_transfer: bool = False

    @field_validator("deck")
    @classmethod
    def _check_deck(cls, deck: str) -> str:
        """Refuse deck names with empty ``::`` levels.

        Args:
            deck: Stripped deck name, possibly empty.

        Returns:
            The deck name with whitespace around every level removed.

        Raises:
            ValueError: If a level between ``::`` is empty.
        """
        return normalize_deck(deck) if deck else deck

    def generator_values(self) -> dict[str, Any]:
        """Return only the explicitly set values for the generator.

        Returns:
            A mapping in the format of ``resolve_generate_settings`` without
            paths: non-empty texts, set numbers and enums (as enum objects),
            and the yes/no options the form sent.
        """
        values: dict[str, Any] = {name: getattr(self, name) for name in TEXT_FIELDS}
        values |= {name: getattr(self, name) for name in VALUE_FIELDS + SWITCH_FIELDS}
        return {name: value for name, value in values.items() if value not in ("", None)}


class ExportForm(BaseModel):
    """Hold the deck selected for a card-JSON export.

    Attributes:
        target: New APKG or the local synchronized collection.
        deck: Target deck; empty lets the generator YAML provide its
            generation default.
    """

    model_config = ConfigDict(str_strip_whitespace=True, frozen=True)

    target: ExportTarget = ExportTarget.NEW_APKG
    deck: str = Field(default="", max_length=200)

    @field_validator("deck")
    @classmethod
    def _check_deck(cls, deck: str) -> str:
        """Normalize a non-empty target deck.

        Args:
            deck: Stripped deck name from the export form.

        Returns:
            The normalized deck, or an empty string for the YAML default.

        Raises:
            ValueError: If a non-empty deck has an empty ``::`` level.
        """
        return normalize_deck(deck) if deck else deck


def normalize_deck(deck: str) -> str:
    """Trim every ``::`` level of a deck name and refuse empty levels.

    Args:
        deck: Deck name such as ``Vorlesung :: Kapitel 1``.

    Returns:
        The name with whitespace around every level removed.

    Raises:
        ValueError: If the name or a level between ``::`` is empty.
    """
    levels = [level.strip() for level in deck.split("::")]
    if not all(levels):
        raise ValueError("Deckname mit leerer Ebene; Ebenen werden mit :: getrennt")
    return "::".join(levels)


def form_errors(errors: list[dict[str, Any]], locale: str = "de") -> dict[str, str]:
    """Map Pydantic errors to one message per form field.

    Args:
        errors: ``ValidationError.errors()`` of ``GenerateForm``.
        locale: ``en`` for English; German remains the compatibility default
            for callers outside the web request boundary.

    Returns:
        Field name to message; the first error of a field wins.
    """
    messages: dict[str, str] = {}
    for error in errors:
        field = str(error["loc"][0]) if error["loc"] else "form"
        messages.setdefault(field, error_message(error, locale))
    return messages


def error_message(error: dict[str, Any], locale: str = "de") -> str:
    """Translate one Pydantic error into a short English or German message.

    Args:
        error: One entry of ``ValidationError.errors()``.
        locale: ``en`` for English; any other value uses German.

    Returns:
        A localised template for the error type filled with its context, or
        Pydantic's own message for other error types.
    """
    messages = ENGLISH_MESSAGES if locale == "en" else MESSAGES
    template = messages.get(error["type"])
    if template is None:
        return str(error["msg"])
    return template.format(**(error.get("ctx") or {}))
