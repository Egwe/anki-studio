"""Translate the Anki Studio interface without a runtime dependency."""

from collections.abc import Mapping

from jinja2 import pass_context
from jinja2.runtime import Context
from markupsafe import Markup
from starlette.requests import Request

DEFAULT_LOCALE = "en"
SESSION_LOCALE = "locale"
SUPPORTED_LOCALES = ("en", "de")

# English source messages double as stable catalogue keys. That keeps the
# default locale readable and lets a later language add one mapping instead of
# creating a second set of templates.
GERMAN_TRANSLATIONS: Mapping[str, str] = {
    "Access": "Zugang",
    "Anki Flashcard Generator": "Anki Flashcard Generator",
    "Anki Studio": "Anki Studio",
    "Cancel": "Abbrechen",
    "Change language": "Sprache ändern",
    "Configuration": "Konfiguration",
    "Credentials": "Zugangsdaten",
    "Decks": "Decks",
    "Export": "Export",
    "Generate": "Generieren",
    "Generate cards": "Karten generieren",
    "Generator": "Generator",
    "Interface language": "Oberflächensprache",
    "Jobs": "Jobs",
    "Language": "Sprache",
    "Log in": "Anmelden",
    "Log out": "Abmelden",
    "Models and GPU": "Modelle und GPU",
    "Settings": "Einstellungen",
    "Sync": "Sync",
    "View jobs": "Jobs ansehen",
    "and": "und",
    "Your access settings have been saved. Please log in again.": (
        "Die Zugangseinstellungen wurden gespeichert. Bitte erneut anmelden."
    ),
    "Password": "Passwort",
    "The password is incorrect.": "Das Passwort ist falsch.",
    "No password has been set, so it is not possible to log in yet.": (
        "Es ist noch kein Passwort eingerichtet, deshalb ist keine Anmeldung möglich."
    ),
    "Run <code>anki-studio hash-password</code> on the server.": (
        "Auf dem Server <code>anki-studio hash-password</code> ausführen."
    ),
    "Add the resulting line <code>{hash_env}=…</code> to the environment file, "
    "<code>/etc/anki-studio/env</code> in the container.": (
        "Die ausgegebene Zeile <code>{hash_env}=…</code> in die Umgebungsdatei "
        "eintragen, im Container <code>/etc/anki-studio/env</code>."
    ),
    "Restart the service.": "Den Dienst neu starten.",
    "Create flashcards from documents, review them, and bring them to every device.": (
        "Karteikarten aus Dokumenten erzeugen, prüfen und auf alle Geräte bringen."
    ),
    "Installed components": "Installierte Komponenten",
    "Cards can be reviewed and written, synchronised safely, and exported from the "
    "pages in the navigation.": (
        "Karten prüfen und schreiben, sicher synchronisieren und Karten exportieren: "
        "Die passenden Seiten stehen in der Navigation bereit."
    ),
    "unknown": "unbekannt",
    "queued": "wartet",
    "running": "läuft",
    "done": "fertig",
    "failed": "fehlgeschlagen",
    "cancelled": "abgebrochen",
}


def normalize_locale(value: str | None) -> str:
    """Return a supported locale or the English default.

    Args:
        value: Candidate locale code, usually read from a session or form.

    Returns:
        A member of ``SUPPORTED_LOCALES``. Unsupported or missing values use
        ``DEFAULT_LOCALE``.
    """
    if value in SUPPORTED_LOCALES:
        return value
    return DEFAULT_LOCALE


def locale_from_request(request: Request) -> str:
    """Read the selected interface locale from one request session.

    Args:
        request: HTTP request with Starlette's decoded session.

    Returns:
        The selected supported locale, or English for new and invalid sessions.
    """
    value = request.session.get(SESSION_LOCALE)
    return normalize_locale(value if isinstance(value, str) else None)


def translate(locale: str, message: str, **values: object) -> str:
    """Translate one interface message and interpolate named values.

    Args:
        locale: Requested supported locale.
        message: English catalogue key and default text.
        **values: Named values referenced with ``str.format`` in a message.

    Returns:
        The localised message. Missing translations deliberately fall back to
        English so an incomplete future catalogue never exposes a key.

    Raises:
        KeyError: If a caller omits a named value required by the message.
    """
    translated = message
    if normalize_locale(locale) == "de":
        translated = GERMAN_TRANSLATIONS.get(message, message)
    return translated.format(**values)


def translate_with_fallback(
    locale: str, message: str, *, de: str | None = None, **values: object
) -> str:
    """Translate a non-template message with an optional German fallback.

    Args:
        locale: Selected interface locale, normally captured in a job option.
        message: English catalogue key and default text.
        de: German fallback for a migrated user-facing message.
        **values: Named values referenced with ``str.format`` in the message.

    Returns:
        Localised plain text; unknown locales and missing translations use
        English.
    """
    translated = message
    if normalize_locale(locale) == "de":
        translated = GERMAN_TRANSLATIONS.get(message, de or message)
    return translated.format(**values)


def translate_request(
    request: Request, message: str, *, de: str | None = None, **values: object
) -> str:
    """Translate a route-level message using one request's session locale.

    Args:
        request: Incoming request whose signed session selects a locale.
        message: English catalogue key and default message.
        de: German fallback for a message migrated at the route boundary.
        **values: Named values referenced with ``str.format`` in the message.

    Returns:
        A translated plain-text message suitable for templates and HTTP errors.
    """
    return translate_with_fallback(locale_from_request(request), message, de=de, **values)


@pass_context
def template_translate(
    context: Context, message: str, *, de: str | None = None, **values: object
) -> Markup:
    """Translate a template message using the locale of its request.

    Args:
        context: Jinja render context that contains the HTTP request.
        message: English catalogue key and default text.
        de: German fallback kept with a migrated template message. The central
            catalogue takes precedence and future locales use catalogue entries.
        **values: Named values interpolated by ``translate``.

    Returns:
        Localised text for the current session, or English if no request is
        present (for example when a template is inspected directly in a test).
    """
    request = context.get("request")
    locale = DEFAULT_LOCALE
    if isinstance(request, Request):
        locale = locale_from_request(request)
    translated = message
    if normalize_locale(locale) == "de":
        translated = GERMAN_TRANSLATIONS.get(message, de or message)
    return Markup(translated).format(**values)


@pass_context
def template_status_label(context: Context, status: str) -> str:
    """Translate a persisted job status for a Jinja template.

    Args:
        context: Jinja render context passed through to ``template_translate``.
        status: Job status value from the store.

    Returns:
        The translated label, or the raw status if it is not a known state.
    """
    if status not in {"queued", "running", "done", "failed", "cancelled"}:
        return status
    return template_translate(context, status)


def template_context(request: Request) -> dict[str, object]:
    """Provide common localisation values to every Jinja template.

    Args:
        request: Incoming request being rendered.

    Returns:
        The current locale and the selectable locale codes.
    """
    return {"locale": locale_from_request(request), "supported_locales": SUPPORTED_LOCALES}
