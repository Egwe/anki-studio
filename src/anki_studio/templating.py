"""Provide the Jinja2 templates and values shared by every page."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from fastapi.templating import Jinja2Templates

PACKAGE_DIR = Path(__file__).parent
STATIC_DIR = PACKAGE_DIR / "static"

STATUS_LABELS = {
    "queued": "wartet",
    "running": "läuft",
    "done": "fertig",
    "failed": "fehlgeschlagen",
    "cancelled": "abgebrochen",
}

COMPONENTS = {
    "studio": "anki-studio",
    "generator": "anki-flashcard-generator",
    "anki": "anki",
}


def component_versions() -> dict[str, str]:
    """Read the installed versions of Anki Studio, the generator, and anki.

    Returns:
        Mapping ``studio``, ``generator``, and ``anki`` to version strings;
        a missing distribution is reported as ``unbekannt``.
    """
    return {key: _installed_version(name) for key, name in COMPONENTS.items()}


def _installed_version(distribution: str) -> str:
    """Return the version of one installed distribution.

    Args:
        distribution: Distribution name as installed by uv.

    Returns:
        The version string, or ``unbekannt`` if it is not installed.
    """
    try:
        return version(distribution)
    except PackageNotFoundError:
        return "unbekannt"


def create_templates() -> Jinja2Templates:
    """Create the template renderer with the shared page values.

    Returns:
        Templates loaded from the package's ``templates`` folder; every page
        can use ``versions`` (see ``component_versions``) and
        ``status_labels`` (German job status names).
    """
    templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
    templates.env.globals["versions"] = component_versions()
    templates.env.globals["status_labels"] = STATUS_LABELS
    return templates
