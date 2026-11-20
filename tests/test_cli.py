"""Tests for the ``anki-studio`` command line."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from anki_studio import cli
from anki_studio.passwords import verify_password


@pytest.fixture
def uvicorn_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace ``uvicorn.run`` with a recorder so no server starts.

    Args:
        monkeypatch: Pytest fixture for replacing attributes.

    Returns:
        A list that receives the keyword arguments and app of every call.
    """
    calls: list[dict[str, Any]] = []

    def record(app: FastAPI, **kwargs: Any) -> None:
        """Record one server start.

        Args:
            app: Application that would be served.
            **kwargs: Options passed to uvicorn.
        """
        calls.append({"app": app, **kwargs})

    monkeypatch.setattr(cli.uvicorn, "run", record)
    return calls


def test_serve_uses_settings_file(tmp_path: Path, uvicorn_calls: list[dict[str, Any]]) -> None:
    """``serve --config`` starts uvicorn with host and port from the file.

    Args:
        tmp_path: Temporary test folder.
        uvicorn_calls: Recorded server starts.
    """
    config = tmp_path / "studio.yaml"
    config.write_text("host: 0.0.0.0\nport: 8123\n", encoding="utf-8")

    assert cli.main(["serve", "--config", str(config)]) == 0
    assert len(uvicorn_calls) == 1
    call = uvicorn_calls[0]
    assert (call["host"], call["port"]) == ("0.0.0.0", 8123)
    assert call["app"].state.settings.port == 8123


def test_serve_rejects_invalid_settings(
    tmp_path: Path, uvicorn_calls: list[dict[str, Any]], capsys: pytest.CaptureFixture[str]
) -> None:
    """Invalid settings end with exit code 1 and a message, no server starts.

    Args:
        tmp_path: Temporary test folder.
        uvicorn_calls: Recorded server starts.
        capsys: Pytest fixture capturing console output.
    """
    config = tmp_path / "studio.yaml"
    config.write_text("port: 0\n", encoding="utf-8")

    assert cli.main(["serve", "--config", str(config)]) == 1
    assert uvicorn_calls == []
    assert "Ungültige Einstellungen" in capsys.readouterr().err


def test_serve_rejects_invalid_secrets(
    monkeypatch: pytest.MonkeyPatch,
    uvicorn_calls: list[dict[str, Any]],
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An invalid session key stops the start without showing its value.

    Args:
        monkeypatch: Pytest fixture for environment changes.
        uvicorn_calls: Recorded server starts.
        capsys: Pytest fixture capturing console output.
    """
    monkeypatch.delenv("ANKI_STUDIO_CONFIG", raising=False)
    monkeypatch.setenv("ANKI_STUDIO_SESSION_SECRET", "zu-kurz-und-geheim")

    assert cli.main(["serve"]) == 1
    assert uvicorn_calls == []
    error = capsys.readouterr().err
    assert "ANKI_STUDIO_SESSION_SECRET" in error
    assert "zu-kurz-und-geheim" not in error


def answer_prompts(monkeypatch: pytest.MonkeyPatch, *answers: str) -> None:
    """Feed fixed answers to the password prompts.

    Args:
        monkeypatch: Pytest fixture for replacing attributes.
        *answers: Inputs returned by consecutive ``getpass`` calls.
    """
    replies = iter(answers)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt: next(replies))


def test_hash_password_prints_environment_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Matching inputs print one verifiable ``ANKI_STUDIO_PASSWORD_HASH`` line.

    Args:
        monkeypatch: Pytest fixture for replacing attributes.
        capsys: Pytest fixture capturing console output.
    """
    answer_prompts(monkeypatch, "richtig-geheim", "richtig-geheim")

    assert cli.main(["hash-password"]) == 0
    name, _, encoded = capsys.readouterr().out.strip().partition("=")
    assert name == "ANKI_STUDIO_PASSWORD_HASH"
    assert verify_password("richtig-geheim", encoded)


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        (("richtig-geheim", "anders-geheim"), "stimmen nicht überein"),
        (("kurz", "kurz"), "mindestens 8"),
    ],
)
def test_hash_password_rejects_bad_input(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    answers: tuple[str, str],
    message: str,
) -> None:
    """Different or too short inputs end with exit code 1 and no output line.

    Args:
        monkeypatch: Pytest fixture for replacing attributes.
        capsys: Pytest fixture capturing console output.
        answers: The two inputs.
        message: Expected part of the error message.
    """
    answer_prompts(monkeypatch, *answers)

    assert cli.main(["hash-password"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert message in output.err


def test_command_is_required() -> None:
    """Calling the program without a command is a usage error."""
    with pytest.raises(SystemExit) as exit_info:
        cli.main([])

    assert exit_info.value.code == 2
