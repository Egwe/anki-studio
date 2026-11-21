"""Change the generator YAML through the interface (AS-009, AS-016).

Every change is applied to the configuration as data, validated by the
generator's ``AppConfig`` and saved atomically with its ``save_config``.
Comments in the file are not kept. Standard profiles of the template can
be reset but not deleted, because the start would add them again (AS-015).
"""

import re
from pathlib import Path
from typing import Any

import yaml
from anki_flashcards.config import AppConfig, save_config
from pydantic import ValidationError

from anki_studio.forms import error_message
from anki_studio.generator_config import load_generator_config

PROFILE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}")
PROFILE_FIELDS = ("model", "api_base", "api_key_env", "timeout", "pdf_mode", "image_input")
GENERATION_FIELDS = (
    "deck",
    "limit",
    "language",
    "instructions",
    "chunk_size",
    "timeout",
    "pdf_mode",
    "subdecks",
)
CONVERSION_FIELDS = (
    "force_ocr",
    "formulas",
    "allow_unreadable",
    "allow_cpu",
    "formula_batch_size",
)
PICTURE_FIELDS = ("backend", "model", "profile")


class ConfigEditError(ValueError):
    """Report refused changes with one German message per field.

    Attributes:
        errors: Field name to message; ``form`` for the whole change.
    """

    def __init__(self, errors: dict[str, str]) -> None:
        """Store the messages.

        Args:
            errors: Field name to message.
        """
        super().__init__("; ".join(f"{name}: {text}" for name, text in errors.items()))
        self.errors = errors


def save_profile(path: Path, name: str, fields: dict[str, str], *, new: bool) -> AppConfig:
    """Create or replace one model profile.

    Args:
        path: Generator YAML.
        name: Profile name; new names use lower-case letters, digits, ``-``
            and ``_``.
        fields: Entered values of ``PROFILE_FIELDS`` plus ``options`` as
            YAML mapping text; empty optional values mean "not set".
        new: Whether the profile must not exist yet.

    Returns:
        The saved configuration.

    Raises:
        ConfigEditError: If the name is invalid or taken, the profile is
            unknown, or the generator's schema refuses the values.
    """
    raw = _raw(path)
    _check_profile_name(raw, name, new=new)
    profile = {key: _blank_to_none(fields.get(key, "")) for key in PROFILE_FIELDS}
    profile["options"] = _options(fields.get("options", ""))
    raw.setdefault("models", {})[name] = {k: v for k, v in profile.items() if v is not None}
    return _store(path, raw)


def delete_profile(path: Path, name: str, protected: set[str]) -> AppConfig:
    """Remove a profile that is neither a standard profile nor in use.

    Args:
        path: Generator YAML.
        name: Profile to remove.
        protected: Names of the template's standard profiles.

    Returns:
        The saved configuration.

    Raises:
        ConfigEditError: If the profile is standard, unknown, or referenced
            as default or picture profile.
    """
    if name in protected:
        raise ConfigEditError({"form": "Standardprofile lassen sich nur zurücksetzen."})
    raw = _raw(path)
    if raw.get("models", {}).pop(name, None) is None:
        raise ConfigEditError({"form": f"Profil „{name}“ gibt es nicht."})
    return _store(path, raw)


def reset_profile(path: Path, name: str, template: AppConfig) -> AppConfig:
    """Replace a standard profile with its template version.

    Args:
        path: Generator YAML.
        name: Standard profile.
        template: Configuration of the bundled template.

    Returns:
        The saved configuration.

    Raises:
        ConfigEditError: If the profile is no standard profile.
    """
    if name not in template.models:
        raise ConfigEditError({"form": f"„{name}“ ist kein Standardprofil."})
    raw = _raw(path)
    raw.setdefault("models", {})[name] = template.models[name].model_dump(
        mode="json", exclude_none=True
    )
    return _store(path, raw)


def save_defaults(path: Path, fields: dict[str, str]) -> AppConfig:
    """Save the default profile, generation defaults, and conversion settings.

    Args:
        path: Generator YAML.
        fields: Entered values: ``default_profile``, ``generation.*``,
            ``pdf_conversion.*`` (``ocr_languages`` separated by spaces or
            commas) and ``pictures.*``; empty optional values mean "not set".

    Returns:
        The saved configuration.

    Raises:
        ConfigEditError: If the generator's schema refuses the values.
    """
    raw = _raw(path)
    raw["default_profile"] = _blank_to_none(fields.get("default_profile", ""))
    generation = raw.setdefault("generation", {})
    generation.pop("profile", None)
    generation |= {
        key: _blank_to_none(fields.get(f"generation.{key}", "")) for key in GENERATION_FIELDS
    }
    generation["instructions"] = fields.get("generation.instructions", "")
    conversion = raw.setdefault("pdf_conversion", {})
    conversion |= {
        key: _blank_to_none(fields.get(f"pdf_conversion.{key}", "")) for key in CONVERSION_FIELDS
    }
    conversion["ocr_languages"] = re.split(
        r"[\s,]+", fields.get("pdf_conversion.ocr_languages", "").strip()
    )
    pictures = conversion.setdefault("pictures", {})
    pictures |= {key: _blank_to_none(fields.get(f"pictures.{key}", "")) for key in PICTURE_FIELDS}
    return _store(path, _without_none(raw))


def replace_config(path: Path, text: str) -> AppConfig:
    """Replace the whole generator YAML with an uploaded file after validation.

    Args:
        path: Generator YAML.
        text: Content of the uploaded file.

    Returns:
        The saved configuration.

    Raises:
        ConfigEditError: If the text is no YAML mapping or the schema refuses it.
    """
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ConfigEditError({"file": "Die Datei ist kein gültiges YAML."}) from error
    if not isinstance(raw, dict):
        raise ConfigEditError({"file": "Die Datei muss Schlüssel und Werte enthalten."})
    return _store(path, raw)


def _check_profile_name(raw: dict[str, Any], name: str, *, new: bool) -> None:
    """Check a profile name for creating or editing.

    Args:
        raw: Current configuration data.
        name: Profile name.
        new: Whether a new profile is created.

    Returns:
        None.

    Raises:
        ConfigEditError: For invalid, reserved, taken, or unknown names.
    """
    exists = name in raw.get("models", {})
    if new and (not PROFILE_NAME.fullmatch(name) or name == "cli"):
        raise ConfigEditError(
            {
                "name": "Name aus Kleinbuchstaben, Ziffern, - und _ (höchstens 63 Zeichen); "
                "nicht „cli“."
            }
        )
    if new and exists:
        raise ConfigEditError({"name": f"Profil „{name}“ gibt es schon."})
    if not new and not exists:
        raise ConfigEditError({"form": f"Profil „{name}“ gibt es nicht."})


def _options(text: str) -> dict[str, Any]:
    """Parse provider options entered as YAML mapping.

    Args:
        text: Lines like ``temperature: 0.2``; empty for no options.

    Returns:
        The options mapping.

    Raises:
        ConfigEditError: If the text is no YAML mapping.
    """
    if not text.strip():
        return {}
    try:
        options = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ConfigEditError({"options": "Optionen bitte als „name: wert“ je Zeile."}) from error
    if not isinstance(options, dict):
        raise ConfigEditError({"options": "Optionen bitte als „name: wert“ je Zeile."})
    return options


def _raw(path: Path) -> dict[str, Any]:
    """Load the current configuration as plain data.

    Args:
        path: Generator YAML.

    Returns:
        The validated configuration dumped to JSON-safe data.
    """
    return load_generator_config(path).config.model_dump(mode="json", exclude_none=True)


def _store(path: Path, raw: dict[str, Any]) -> AppConfig:
    """Validate configuration data and save it atomically.

    Args:
        path: Generator YAML.
        raw: Complete configuration data.

    Returns:
        The saved configuration.

    Raises:
        ConfigEditError: With German messages per field if the schema
            refuses the data.
    """
    try:
        config = AppConfig.model_validate(raw)
    except ValidationError as error:
        raise ConfigEditError(_errors(error)) from error
    save_config(path, config)
    return config


def _errors(error: ValidationError) -> dict[str, str]:
    """Map schema errors to the field names used in the forms.

    Args:
        error: Validation error of ``AppConfig``.

    Returns:
        Field name to message; errors of the whole file use ``form``.
    """
    messages: dict[str, str] = {}
    for item in error.errors():
        location = [str(part) for part in item["loc"]]
        messages.setdefault(_field_key(location), error_message(item))
    return messages


def _field_key(location: list[str]) -> str:
    """Name the form field of an error location.

    Args:
        location: Path of the error in the configuration.

    Returns:
        ``generation.limit`` style keys for defaults, the plain field name
        for profiles (``models.<name>.<field>``), or ``form``.
    """
    if not location:
        return "form"
    if location[0] == "models" and len(location) >= 3:
        return location[2]
    if location[0] == "pdf_conversion" and len(location) >= 3 and location[1] == "pictures":
        return f"pictures.{location[2]}"
    return ".".join(location[:2])


def _blank_to_none(value: Any) -> Any:
    """Treat blank form values as not set.

    Args:
        value: Entered value.

    Returns:
        None for empty or whitespace-only strings, otherwise the stripped
        string or the value unchanged.
    """
    if isinstance(value, str):
        return value.strip() or None
    return value


def _without_none(data: Any) -> Any:
    """Remove keys whose value is None so schema defaults apply.

    Args:
        data: Nested configuration data.

    Returns:
        The data without None values in mappings.
    """
    if isinstance(data, dict):
        return {key: _without_none(value) for key, value in data.items() if value is not None}
    return data
