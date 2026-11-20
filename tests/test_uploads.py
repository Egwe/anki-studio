"""Tests for storing uploaded documents (AS-033)."""

import io
from pathlib import Path

import pytest

from anki_studio import uploads
from anki_studio.uploads import (
    APKG,
    UploadError,
    UploadKind,
    check_upload,
    clean_filename,
    store_upload,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Skript.PDF", "Skript.pdf"),
        ("../../etc/passwd.txt", "passwd.txt"),
        ("C:\\Users\\me\\Vorlesung 3.docx", "Vorlesung 3.docx"),
        ("Übung<1>|?.md", "Übung_1_.md"),
        (".hidden.txt", "hidden.txt"),
        ("...", "upload"),
        ("", "upload"),
        (None, "upload"),
        ("noext", "noext"),
    ],
)
def test_clean_filename(raw: str | None, expected: str) -> None:
    """Paths, unsafe characters, and leading dots are removed.

    Args:
        raw: File name from the browser.
        expected: Cleaned file name.
    """
    assert clean_filename(raw) == expected


def test_clean_filename_limits_length() -> None:
    """Long names are shortened but keep their suffix."""
    name = clean_filename("a" * 300 + ".pdf")

    assert len(name) == 120
    assert name.endswith(".pdf")


@pytest.mark.parametrize("name", ["bild.png", "skript", "archiv.pdf.zip"])
def test_unsupported_types_are_refused(name: str) -> None:
    """Only the generator's document types are accepted.

    Args:
        name: Cleaned file name with an unsupported suffix.
    """
    with pytest.raises(UploadError, match="nicht unterstützt"):
        check_upload(name, 10)


def test_reported_size_is_checked_before_writing(tmp_path: Path) -> None:
    """A reported size above 100 MiB is refused without touching the folder.

    Args:
        tmp_path: Temporary upload folder.
    """
    with pytest.raises(UploadError, match="100 MiB"):
        store_upload(io.BytesIO(b"x"), "skript.pdf", tmp_path, size=100 * 1024 * 1024 + 1)

    assert list(tmp_path.iterdir()) == []


def test_store_upload_writes_file(tmp_path: Path) -> None:
    """An accepted upload is stored under its cleaned name.

    Args:
        tmp_path: Temporary upload folder.
    """
    path = store_upload(io.BytesIO(b"Inhalt"), "notizen.md", tmp_path, size=6)

    assert path == tmp_path / "notizen.md"
    assert path.read_bytes() == b"Inhalt"
    assert [entry.name for entry in tmp_path.iterdir()] == ["notizen.md"]


def test_wrong_reported_size_is_caught_while_copying(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Too much data is detected while copying and leaves no file behind.

    Args:
        tmp_path: Temporary upload folder.
        monkeypatch: Pytest fixture to lower the limit for the test.
    """
    monkeypatch.setattr(uploads, "COPY_CHUNK", 4)
    tiny = UploadKind(frozenset({".md"}), 10)

    with pytest.raises(UploadError, match="größer als"):
        store_upload(io.BytesIO(b"x" * 11), "notizen.md", tmp_path, size=5, kind=tiny)

    assert list(tmp_path.iterdir()) == []


def test_exact_limit_is_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A file of exactly the limit is stored.

    Args:
        tmp_path: Temporary upload folder.
        monkeypatch: Pytest fixture to lower the limit for the test.
    """
    monkeypatch.setattr(uploads, "COPY_CHUNK", 4)
    tiny = UploadKind(frozenset({".md"}), 10)

    path = store_upload(io.BytesIO(b"x" * 10), "notizen.md", tmp_path, kind=tiny)

    assert path.stat().st_size == 10


def test_apkg_kind_accepts_packages_up_to_512_mib() -> None:
    """Packages to extend have their own type and a larger limit."""
    check_upload("deck.apkg", 512 * 2**20, APKG)

    with pytest.raises(UploadError, match="512 MiB"):
        check_upload("deck.apkg", 512 * 2**20 + 1, APKG)
    with pytest.raises(UploadError, match="nicht unterstützt"):
        check_upload("deck.pdf", 10, APKG)
