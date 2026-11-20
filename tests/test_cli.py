"""Tests for the ``anki-studio`` command line."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from anki_studio import cli


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


def test_command_is_required() -> None:
    """Calling the program without a command is a usage error."""
    with pytest.raises(SystemExit) as exit_info:
        cli.main([])

    assert exit_info.value.code == 2
