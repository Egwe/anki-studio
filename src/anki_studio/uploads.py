"""Store uploaded documents safely inside a job folder (AS-033).

The browser's file name is only used for display and, after cleaning, as
the stored name; it never decides the directory. The size is checked
before anything is written to the job folder.
"""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from anki_flashcards.documents import MAX_FILE_SIZE, SUPPORTED_SUFFIXES

MAX_NAME_LENGTH = 120
COPY_CHUNK = 1024 * 1024
UNSAFE_CHARACTERS = re.compile(r"[^\w.\- ]+")


class UploadError(ValueError):
    """Report an upload that is refused, in words for the user."""


@dataclass(frozen=True)
class UploadKind:
    """Describe which files an upload field accepts.

    Attributes:
        suffixes: Allowed lower-case suffixes including the dot.
        max_size: Largest accepted file in bytes.
    """

    suffixes: frozenset[str]
    max_size: int

    @property
    def limit_text(self) -> str:
        """Return the size limit for messages.

        Returns:
            The limit in whole MiB, for example ``100 MiB``.
        """
        return f"{self.max_size // 2**20} MiB"


DOCUMENT = UploadKind(frozenset(SUPPORTED_SUFFIXES), MAX_FILE_SIZE)
APKG = UploadKind(frozenset({".apkg"}), 512 * 2**20)
CARD_JSON = UploadKind(frozenset({".json"}), MAX_FILE_SIZE)


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


def check_upload(name: str, size: int | None, kind: UploadKind = DOCUMENT) -> None:
    """Refuse unsupported file types and files above the limit.

    Args:
        name: Cleaned file name.
        size: Size in bytes as reported by the upload, or None if unknown.
        kind: Accepted suffixes and limit; documents by default (the
            generator's types and its 100 MiB limit).

    Returns:
        None if the upload may be stored.

    Raises:
        UploadError: If the suffix is not allowed or the size exceeds the
            limit.
    """
    suffix = Path(name).suffix.lower()
    if suffix not in kind.suffixes:
        allowed = ", ".join(sorted(kind.suffixes))
        raise UploadError(f"Dateityp „{suffix or 'ohne Endung'}“ wird nicht unterstützt: {allowed}")
    if size is not None and size > kind.max_size:
        raise UploadError(f"„{name}“ ist größer als {kind.limit_text}.")


def store_upload(
    source: BinaryIO,
    name: str,
    folder: Path,
    size: int | None = None,
    kind: UploadKind = DOCUMENT,
) -> Path:
    """Check an upload and copy it into a folder, never above its limit.

    The size is checked before writing; while copying into a hidden
    ``.part`` file, the bytes are counted again in case the reported size
    was wrong. Only a complete copy is renamed to its final name; a refused
    or broken copy leaves no file behind.

    Args:
        source: Readable binary stream of the uploaded file.
        name: Cleaned file name from ``clean_filename``.
        folder: Existing upload folder of one job.
        size: Size reported by the upload, or None.
        kind: Accepted suffixes and limit.

    Returns:
        Path of the stored file inside ``folder``.

    Raises:
        UploadError: If the type is unsupported or the file is too large.
        OSError: If writing fails; the partial file is removed.
    """
    check_upload(name, size, kind)
    target = folder / name
    partial = folder / f".{name}.part"
    try:
        with partial.open("xb") as output:
            _copy_limited(source, output, name, kind)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return target


def _copy_limited(source: BinaryIO, output: BinaryIO, name: str, kind: UploadKind) -> None:
    """Copy a stream in 1 MiB chunks and stop above the limit.

    Args:
        source: Readable binary stream.
        output: Writable binary stream.
        name: File name used in the error message.
        kind: Upload kind whose limit applies.

    Returns:
        None.

    Raises:
        UploadError: As soon as more bytes than the limit were read.
    """
    written = 0
    while chunk := source.read(COPY_CHUNK):
        written += len(chunk)
        if written > kind.max_size:
            raise UploadError(f"„{name}“ ist größer als {kind.limit_text}.")
        output.write(chunk)
