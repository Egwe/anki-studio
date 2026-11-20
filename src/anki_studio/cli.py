"""Command line entry point ``anki-studio``."""

import argparse
import getpass
import sys
from pathlib import Path

import uvicorn

from anki_studio.app import create_app
from anki_studio.credentials import PASSWORD_HASH_ENV
from anki_studio.passwords import hash_password
from anki_studio.settings import CONFIG_ENV, SettingsError, load_settings, settings_path


def build_parser() -> argparse.ArgumentParser:
    """Describe the commands and options of ``anki-studio``.

    Returns:
        A parser whose namespaces carry the command function as ``handler``.
    """
    parser = argparse.ArgumentParser(
        prog="anki-studio",
        description="Web-Oberfläche für den Anki Flashcard Generator.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="Web-Oberfläche starten")
    serve.add_argument(
        "--config",
        type=Path,
        help=f"studio.yaml; ohne Angabe gilt {CONFIG_ENV} oder die Standardwerte",
    )
    serve.set_defaults(handler=serve_command)
    hash_command = commands.add_parser(
        "hash-password",
        help=f"Login-Passwort abfragen und die Zeile {PASSWORD_HASH_ENV}=… ausgeben",
    )
    hash_command.set_defaults(handler=hash_password_command)
    return parser


def hash_password_command(args: argparse.Namespace) -> int:
    """Ask twice for a new password and print the environment line with its hash.

    The prompts go to the terminal; only the line for the environment file
    is written to standard output, so it can be appended with ``>>``.

    Args:
        args: Parsed options; the command has none.

    Returns:
        0 after printing, 1 if the inputs differ or the password is too short.
    """
    password = getpass.getpass("Neues Passwort: ")
    if getpass.getpass("Passwort wiederholen: ") != password:
        print("Fehler: Die Eingaben stimmen nicht überein.", file=sys.stderr)
        return 1
    try:
        encoded = hash_password(password)
    except ValueError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1
    print(f"{PASSWORD_HASH_ENV}={encoded}")
    return 0


def serve_command(args: argparse.Namespace) -> int:
    """Load the settings and run the web server until it is stopped.

    Exactly one uvicorn process serves the application, because the Anki
    collection must only be used by one process.

    Args:
        args: Parsed options; ``config`` is an optional settings path.

    Returns:
        0 after a regular shutdown, 1 if the settings are invalid.
    """
    try:
        settings = load_settings(settings_path(args.config))
    except SettingsError as error:
        print(f"Fehler: {error}", file=sys.stderr)
        return 1
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, server_header=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Parse the command line and run the selected command.

    Args:
        argv: Arguments without the program name; None reads ``sys.argv``.

    Returns:
        The exit code of the command.
    """
    args = build_parser().parse_args(argv)
    return args.handler(args)


def run() -> None:
    """Run ``main`` and exit the process with its exit code.

    Returns:
        None; the function ends the process.
    """
    sys.exit(main())
