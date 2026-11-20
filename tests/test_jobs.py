"""Tests for the job folders (AS-032)."""

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from anki_studio.jobs import EVENTS_FILE, JOB_FILE, RESTART_MESSAGE, JobStatus, JobStore
from anki_studio.uploads import APKG, UploadError


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    """Provide an empty job store in a temporary folder.

    Args:
        tmp_path: Temporary test folder.

    Returns:
        A store rooted at ``<tmp_path>/jobs``.
    """
    return JobStore(tmp_path / "jobs")


def add_job(store: JobStore, name: str = "skript.md", content: bytes = b"# Titel") -> str:
    """Create a job with a small Markdown upload.

    Args:
        store: Job store.
        name: File name sent by the browser.
        content: File content.

    Returns:
        The identifier of the new job.
    """
    return store.create(io.BytesIO(content), name, len(content), {"deck": "Test"}).id


def test_create_stores_upload_and_state(store: JobStore) -> None:
    """A new job gets its folder, the upload, and a queued state.

    Args:
        store: Empty job store.
    """
    job = store.create(io.BytesIO(b"# Titel"), "../Skript.MD", 7, {"deck": "Test"})

    assert job.status is JobStatus.QUEUED
    assert job.source_name == "Skript.md"
    assert job.options == {"deck": "Test"}
    assert store.upload_path(job).read_bytes() == b"# Titel"
    assert json.loads((store.job_dir(job.id) / JOB_FILE).read_text())["status"] == "queued"


@pytest.mark.parametrize(("name", "size"), [("bild.png", 10), ("skript.pdf", 200 * 2**20)])
def test_refused_upload_leaves_no_folder(store: JobStore, name: str, size: int) -> None:
    """Wrong type or size is refused before a job folder exists.

    Args:
        store: Empty job store.
        name: Uploaded file name.
        size: Reported size.
    """
    with pytest.raises(UploadError):
        store.create(io.BytesIO(b"x"), name, size)

    assert list(store.root.iterdir()) == []


def test_get_rejects_invalid_and_unknown_ids(store: JobStore) -> None:
    """Invalid identifiers never reach the file system.

    Args:
        store: Empty job store.
    """
    assert store.get("../../etc") is None
    assert store.get("0" * 32) is None
    with pytest.raises(ValueError, match="Ungültige Job-ID"):
        store.job_dir("../x")


def test_jobs_survive_a_new_store(store: JobStore) -> None:
    """A restarted application sees the same jobs, newest first.

    Args:
        store: Empty job store.
    """
    first, second = add_job(store), add_job(store)

    jobs = JobStore(store.root).list_jobs()

    assert [job.id for job in jobs] == [second, first]


def test_update_changes_status_and_message(store: JobStore) -> None:
    """Status changes are stored with message and new timestamp.

    Args:
        store: Empty job store.
    """
    job_id = add_job(store)
    before = store.get(job_id)

    updated = store.update(job_id, JobStatus.FAILED, "Provider nicht erreichbar")

    assert store.get(job_id) == updated
    assert updated.status is JobStatus.FAILED
    assert updated.message == "Provider nicht erreichbar"
    assert updated.updated_at >= before.updated_at


def test_update_unknown_job_raises(store: JobStore) -> None:
    """Updating a missing job is an error.

    Args:
        store: Empty job store.
    """
    with pytest.raises(KeyError):
        store.update("0" * 32, JobStatus.DONE)


def test_events_are_appended_and_read_incrementally(store: JobStore) -> None:
    """Events keep their order and can be read from a position on.

    Args:
        store: Empty job store.
    """
    job_id = add_job(store)
    assert store.read_events(job_id) == []

    store.append_event(job_id, {"type": "notice", "text": "Übertragung", "level": "transfer"})
    store.append_event(job_id, {"type": "stage_finished", "stage": "generation"})

    assert [event["type"] for event in store.read_events(job_id)] == ["notice", "stage_finished"]
    assert store.read_events(job_id, start=1) == [{"type": "stage_finished", "stage": "generation"}]
    assert "Übertragung" in (store.job_dir(job_id) / EVENTS_FILE).read_text(encoding="utf-8")


def test_recover_cancels_unfinished_jobs(store: JobStore) -> None:
    """After a restart queued and running jobs count as cancelled.

    Args:
        store: Empty job store.
    """
    queued, running, done = add_job(store), add_job(store), add_job(store)
    store.update(running, JobStatus.RUNNING)
    store.update(done, JobStatus.DONE)

    assert sorted(store.recover()) == sorted([queued, running])
    assert store.get(running).status is JobStatus.CANCELLED
    assert store.get(running).message == RESTART_MESSAGE
    assert store.get(done).status is JobStatus.DONE


def test_remove_expired_keeps_recent_and_unfinished(store: JobStore) -> None:
    """Only finished jobs older than the retention period are deleted.

    Args:
        store: Empty job store.
    """
    old_done, old_queued, new_done = add_job(store), add_job(store), add_job(store)
    store.update(old_done, JobStatus.DONE)
    store.update(new_done, JobStatus.DONE)
    later = datetime.now(UTC) + timedelta(days=20)

    removed = store.remove_expired(timedelta(days=14), now=later)

    assert set(removed) == {old_done, new_done}
    assert store.get(old_queued) is not None
    assert store.remove_expired(timedelta(days=14)) == []


def test_unreadable_job_file_is_skipped(store: JobStore) -> None:
    """A broken ``job.json`` does not break the job list.

    Args:
        store: Empty job store.
    """
    good = add_job(store)
    broken = add_job(store)
    (store.job_dir(broken) / JOB_FILE).write_text("{kaputt", encoding="utf-8")

    assert [job.id for job in store.list_jobs()] == [good]


def test_add_file_and_delete(store: JobStore) -> None:
    """An extra upload lands in its subfolder; delete removes the job.

    Args:
        store: Empty job store.
    """
    job_id = add_job(store)

    name = store.add_file(job_id, "target", io.BytesIO(b"PK"), "../Mein Deck.APKG", 2, APKG)

    assert name == "Mein Deck.apkg"
    assert (store.job_dir(job_id) / "target" / name).read_bytes() == b"PK"
    with pytest.raises(UploadError):
        store.add_file(job_id, "target", io.BytesIO(b"x"), "deck.pdf", 1, APKG)
    store.delete(job_id)
    assert store.get(job_id) is None
