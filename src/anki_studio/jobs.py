"""Keep generation jobs as folders below the data directory (AS-032).

Layout of one job::

    jobs/<id>/job.json        state of the job (atomically replaced)
    jobs/<id>/events.jsonl    one JSON event per line, appended
    jobs/<id>/upload/<name>   the uploaded document

Later packages add the card JSON and results to the same folder.
"""

import json
import logging
import os
import re
import secrets
import shutil
import threading
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, BinaryIO

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from anki_studio.uploads import UploadError, UploadKind, check_upload, clean_filename, store_upload

JOB_ID = re.compile(r"[0-9a-f]{32}")
JOB_FILE = "job.json"
EVENTS_FILE = "events.jsonl"
UPLOAD_DIR = "upload"
RESTART_MESSAGE = "Durch einen Neustart von Anki Studio abgebrochen."

logger = logging.getLogger(__name__)


class JobStatus(StrEnum):
    """Name the stages of a job's life."""

    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def finished(self) -> bool:
        """Tell whether the job will not run anymore.

        Returns:
            True for done, failed, and cancelled jobs.
        """
        return self in {JobStatus.DONE, JobStatus.FAILED, JobStatus.CANCELLED}


class Job(BaseModel):
    """Describe one job as stored in ``job.json``.

    Attributes:
        id: 32 hexadecimal characters, also the folder name.
        status: Current stage.
        created_at: Creation time (UTC).
        updated_at: Time of the last status change (UTC).
        source_name: Cleaned name of the uploaded file.
        message: Error or cancellation reason for the user, or None.
        options: Validated, JSON-safe job options chosen in the form.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime
    updated_at: datetime
    source_name: str
    message: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)


class JobStore:
    """Create, read, and update job folders; safe to use from several threads.

    Attributes:
        root: Absolute folder that holds one subfolder per job.
    """

    def __init__(self, root: Path) -> None:
        """Use a jobs folder and create it if missing.

        Args:
            root: Absolute jobs folder, for example ``<data_dir>/jobs``.
        """
        self.root = root
        self._lock = threading.Lock()
        root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        """Return the folder of one job.

        Args:
            job_id: Identifier of 32 hexadecimal characters.

        Returns:
            Path below ``root``; it may not exist.

        Raises:
            ValueError: If ``job_id`` is not a valid identifier.
        """
        if not JOB_ID.fullmatch(job_id):
            raise ValueError(f"Ungültige Job-ID: {job_id!r}")
        return self.root / job_id

    def upload_path(self, job: Job) -> Path:
        """Return the stored document of a job.

        Args:
            job: Existing job.

        Returns:
            Absolute path of the uploaded file.
        """
        return self.job_dir(job.id) / UPLOAD_DIR / job.source_name

    def create(
        self,
        source: BinaryIO,
        filename: str | None,
        size: int | None,
        options: dict[str, Any] | None = None,
    ) -> Job:
        """Store an upload in a new job folder and queue the job.

        Type and size are checked before the folder is created; if storing
        fails, the folder is removed again.

        Args:
            source: Readable stream of the uploaded document.
            filename: File name sent by the browser.
            size: Reported size in bytes, or None.
            options: JSON-safe options of the job.

        Returns:
            The new job with status ``queued``.

        Raises:
            UploadError: If the type is unsupported or the file is too large.
            OSError: If the folder or file cannot be written.
        """
        name = clean_filename(filename)
        check_upload(name, size)
        job_id = secrets.token_hex(16)
        folder = self.job_dir(job_id)
        (folder / UPLOAD_DIR).mkdir(parents=True)
        try:
            store_upload(source, name, folder / UPLOAD_DIR, size)
        except (UploadError, OSError):
            shutil.rmtree(folder, ignore_errors=True)
            raise
        now = _now()
        job = Job(
            id=job_id, created_at=now, updated_at=now, source_name=name, options=options or {}
        )
        self._write(job)
        return job

    def add_file(
        self,
        job_id: str,
        subfolder: str,
        source: BinaryIO,
        filename: str | None,
        size: int | None,
        kind: UploadKind,
    ) -> str:
        """Store an additional upload, for example an APKG to extend.

        Args:
            job_id: Identifier of an existing job.
            subfolder: Folder name inside the job folder, such as ``target``.
            source: Readable stream of the uploaded file.
            filename: File name sent by the browser.
            size: Reported size in bytes, or None.
            kind: Accepted suffixes and size limit.

        Returns:
            The cleaned file name inside ``subfolder``.

        Raises:
            UploadError: If the type is not allowed or the file is too large.
            OSError: If the file cannot be written.
        """
        name = clean_filename(filename)
        folder = self.job_dir(job_id) / subfolder
        folder.mkdir(exist_ok=True)
        store_upload(source, name, folder, size, kind)
        return name

    def delete(self, job_id: str) -> None:
        """Remove a job folder completely.

        Args:
            job_id: Identifier of the job.

        Returns:
            None; a missing folder is ignored.
        """
        shutil.rmtree(self.job_dir(job_id), ignore_errors=True)

    def get(self, job_id: str) -> Job | None:
        """Read one job.

        Args:
            job_id: Identifier from a URL or the queue.

        Returns:
            The job, or None if the identifier is invalid or unknown.
        """
        if not JOB_ID.fullmatch(job_id):
            return None
        return self._read(self.root / job_id / JOB_FILE)

    def list_jobs(self) -> list[Job]:
        """Read all jobs, newest first; unreadable folders are skipped.

        Returns:
            Jobs sorted by creation time, newest first.
        """
        jobs = (self._read(path / JOB_FILE) for path in self.root.iterdir() if _is_job(path))
        return sorted((job for job in jobs if job), key=lambda job: job.created_at, reverse=True)

    def update(self, job_id: str, status: JobStatus, message: str | None = None) -> Job:
        """Change the status of a job and store it atomically.

        Args:
            job_id: Identifier of an existing job.
            status: New status.
            message: Error or cancellation reason, or None.

        Returns:
            The updated job.

        Raises:
            KeyError: If the job does not exist.
        """
        with self._lock:
            job = self.get(job_id)
            if job is None:
                raise KeyError(job_id)
            changed = job.model_copy(
                update={"status": status, "message": message, "updated_at": _now()}
            )
            self._write(changed)
        return changed

    def append_event(self, job_id: str, event: dict[str, Any]) -> None:
        """Append one JSON event to the job's event log.

        Args:
            job_id: Identifier of an existing job.
            event: JSON-serializable event with a ``type`` key.

        Returns:
            None.
        """
        line = json.dumps(event, ensure_ascii=False, default=str) + "\n"
        with self._lock, (self.job_dir(job_id) / EVENTS_FILE).open("a", encoding="utf-8") as log:
            log.write(line)

    def read_events(self, job_id: str, start: int = 0) -> list[dict[str, Any]]:
        """Read the events of a job from a given position on.

        Args:
            job_id: Identifier of an existing job.
            start: Number of events to skip, for incremental reading.

        Returns:
            The events after ``start`` in their original order.
        """
        path = self.job_dir(job_id) / EVENTS_FILE
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines[start:] if line.strip()]

    def recover(self) -> list[str]:
        """Mark jobs that were queued or running at a restart as cancelled.

        Returns:
            Identifiers of the jobs that were cancelled.
        """
        stale = [job.id for job in self.list_jobs() if not job.status.finished]
        for job_id in stale:
            self.update(job_id, JobStatus.CANCELLED, RESTART_MESSAGE)
        return stale

    def remove_expired(self, max_age: timedelta, now: datetime | None = None) -> list[str]:
        """Delete finished jobs whose last change is older than ``max_age``.

        Args:
            max_age: Retention period.
            now: Reference time (UTC); None uses the current time.

        Returns:
            Identifiers of the deleted jobs. Queued and running jobs stay.
        """
        limit = (now or _now()) - max_age
        expired = [
            job.id for job in self.list_jobs() if job.status.finished and job.updated_at < limit
        ]
        for job_id in expired:
            shutil.rmtree(self.job_dir(job_id), ignore_errors=True)
        return expired

    def _write(self, job: Job) -> None:
        """Replace ``job.json`` atomically.

        Args:
            job: Job to store.

        Returns:
            None.
        """
        path = self.job_dir(job.id) / JOB_FILE
        temporary = path.with_suffix(".tmp")
        temporary.write_text(job.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def _read(self, path: Path) -> Job | None:
        """Load a job file.

        Args:
            path: Path of a ``job.json``.

        Returns:
            The job, or None if the file is missing or invalid.
        """
        try:
            return Job.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValidationError) as error:
            logger.warning("Job-Datei nicht lesbar: %s (%s)", path, error)
            return None


def _is_job(path: Path) -> bool:
    """Tell whether a folder entry looks like a job folder.

    Args:
        path: Entry of the jobs folder.

    Returns:
        True for directories named with a valid job identifier.
    """
    return path.is_dir() and JOB_ID.fullmatch(path.name) is not None


def _now() -> datetime:
    """Return the current time in UTC.

    Returns:
        A timezone-aware datetime.
    """
    return datetime.now(UTC)
