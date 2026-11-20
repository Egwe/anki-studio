"""Store uploaded documents safely inside a job folder (AS-033).

The browser's file name is only used for display and, after cleaning, as
the stored name; it never decides the directory. The size is checked
before anything is written to the job folder.
"""

import re
import unicodedata
from pathlib import Path
from typing import BinaryIO

from anki_flashcards.documents import MAX_FILE_SIZE, SUPPORTED_SUFFIXES

MAX_NAME_LENGTH = 120
COPY_CHUNK = 1024 * 1024
UNSAFE_CHARACTERS = re.compile(r"[^\w.\- ]+")


class UploadError(ValueError):
    """Report an upload that is refused, in words for the user."""


def clean_filename(raw: str | None) -> str:
    """Turn a browser-supplied file name into a safe single file name.

    Directory parts (slashes and backslashes) are dropped, characters other than
    letters, digits, ``.``, ``-``, ``_`` and spaces become ``_``, leading
    dots are removed, and the stem is shortened so the name stays below
    120 characters.

    Args:
        raw: File name from the upload form, possibly with a path.

    Returns:
        A non-empty name without directory parts; ``upload`` plus the
        suffix if nothing usable remains.
    """
    name = unicodedata.normalize("NFC", raw or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = UNSAFE_CHARACTERS.sub("_", name).strip(" .")
    stem, dot, suffix = name.rpartition(".")
    if not dot:
        stem, suffix = name, ""
    stem = stem.strip(" .") or "upload"
    suffix = f".{suffix.lower()}" if suffix else ""
    return stem[: MAX_NAME_LENGTH - len(suffix)] + suffix


def check_upload(name: str, size: int | None) -> None:
    """Refuse unsupported file types and files above the generator limit.

    Args:
        name: Cleaned file name.
        size: Size in bytes as reported by the upload, or None if unknown.

    Returns:
        None if the upload may be stored.

    Raises:
        UploadError: If the suffix is unsupported or the size exceeds
            100 MiB (the generator's limit).
    """
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        allowed = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise UploadError(f"Dateityp „{suffix or 'ohne Endung'}“ wird nicht unterstützt: {allowed}")
    if size is not None and size > MAX_FILE_SIZE:
        raise UploadError(f"„{name}“ ist größer als 100 MiB.")


def store_upload(source: BinaryIO, name: str, folder: Path, size: int | None = None) -> Path:
    """Check an upload and copy it into a folder, never above 100 MiB.

    The size is checked before writing; while copying into a hidden
    ``.part`` file, the bytes are counted again in case the reported size
    was wrong. Only a complete copy is renamed to its final name; a refused
    or broken copy leaves no file behind.

    Args:
        source: Readable binary stream of the uploaded file.
        name: Cleaned file name from ``clean_filename``.
        folder: Existing upload folder of one job.
        size: Size reported by the upload, or None.

    Returns:
        Path of the stored file inside ``folder``.

    Raises:
        UploadError: If the type is unsupported or the file is too large.
        OSError: If writing fails; the partial file is removed.
    """
    check_upload(name, size)
    target = folder / name
    partial = folder / f".{name}.part"
    try:
        with partial.open("xb") as output:
            _copy_limited(source, output, name)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def _copy_limited(source: BinaryIO, output: BinaryIO, name: str) -> None:
    """Copy a stream in 1 MiB chunks and stop above 100 MiB.

    Args:
        source: Readable binary stream.
        output: Writable binary stream.
        name: File name used in the error message.

    Returns:
        None.

    Raises:
        UploadError: As soon as more than 100 MiB were read.
    """
    written = 0
    while chunk := source.read(COPY_CHUNK):
        written += len(chunk)
        if written > MAX_FILE_SIZE:
            raise UploadError(f"„{name}“ ist größer als 100 MiB.")
        output.write(chunk)
