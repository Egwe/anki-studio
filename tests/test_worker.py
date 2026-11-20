"""Tests for the background job worker (AS-032)."""

import io
import threading
import time
from collections.abc import Callable, Iterator
from datetime import timedelta
from pathlib import Path

import pytest
from anki_flashcards.errors import FlashcardError, GenerationCancelled

from anki_studio.jobs import Job, JobStatus, JobStore
from anki_studio.worker import (
    CANCELLED_BY_STOP,
    CANCELLED_BY_USER,
    UNEXPECTED_ERROR,
    CancelCheck,
    JobRunner,
    JobWorker,
    Reporter,
)

TIMEOUT = 5.0


def wait_until(condition: Callable[[], bool]) -> None:
    """Wait until a condition holds, failing the test after five seconds.

    Args:
        condition: Function that returns True once the expected state exists.
    """
    deadline = time.monotonic() + TIMEOUT
    while not condition():
        assert time.monotonic() < deadline, "Zustand nicht rechtzeitig erreicht"
        time.sleep(0.01)


def status_of(store: JobStore, job_id: str) -> JobStatus:
    """Read the current status of a job.

    Args:
        store: Job store.
        job_id: Identifier of the job.

    Returns:
        The stored status.
    """
    return store.get(job_id).status


@pytest.fixture
def store(tmp_path: Path) -> JobStore:
    """Provide an empty job store.

    Args:
        tmp_path: Temporary test folder.

    Returns:
        A store rooted at ``<tmp_path>/jobs``.
    """
    return JobStore(tmp_path / "jobs")


@pytest.fixture
def start_worker(store: JobStore) -> Iterator[Callable[[JobRunner], JobWorker]]:
    """Provide a factory that starts workers and stops them after the test.

    Args:
        store: Job store shared with the test.

    Yields:
        A function that starts a worker with the given runner.
    """
    workers: list[JobWorker] = []

    def start(runner: JobRunner) -> JobWorker:
        """Start a worker for the shared store.

        Args:
            runner: Simulated job runner.

        Returns:
            The running worker.
        """
        worker = JobWorker(store, runner, timedelta(days=14))
        worker.start()
        workers.append(worker)
        return worker

    yield start
    for worker in workers:
        worker.stop()


def submit(store: JobStore, worker: JobWorker) -> str:
    """Create a small job and hand it to the worker.

    Args:
        store: Job store.
        worker: Running worker.

    Returns:
        The identifier of the submitted job.
    """
    job = store.create(io.BytesIO(b"# Titel"), "skript.md", 7)
    worker.submit(job)
    return job.id


def test_jobs_run_one_after_another(
    store: JobStore, start_worker: Callable[[JobRunner], JobWorker]
) -> None:
    """Jobs finish in order and never overlap.

    Args:
        store: Job store.
        start_worker: Factory for running workers.
    """
    running, overlaps, order = [], [], []

    def runner(job: Job, report: Reporter, cancel: CancelCheck) -> None:
        """Record the job and whether another one is running.

        Args:
            job: Running job.
            report: Event reporter.
            cancel: Cancellation check.
        """
        overlaps.append(bool(running))
        running.append(job.id)
        time.sleep(0.02)
        order.append(job.id)
        running.remove(job.id)

    worker = start_worker(runner)
    ids = [submit(store, worker) for _ in range(3)]

    wait_until(lambda: all(status_of(store, job_id) is JobStatus.DONE for job_id in ids))
    assert order == ids
    assert not any(overlaps)


def test_events_and_status_changes_are_logged(
    store: JobStore, start_worker: Callable[[JobRunner], JobWorker]
) -> None:
    """Runner events sit between the status events in the log.

    Args:
        store: Job store.
        start_worker: Factory for running workers.
    """

    def runner(job: Job, report: Reporter, cancel: CancelCheck) -> None:
        """Report one notice.

        Args:
            job: Running job.
            report: Event reporter.
            cancel: Cancellation check.
        """
        report({"type": "notice", "text": "Hallo", "level": "info"})

    worker = start_worker(runner)
    job_id = submit(store, worker)
    wait_until(lambda: status_of(store, job_id) is JobStatus.DONE)

    events = store.read_events(job_id)
    assert [(event["type"], event.get("status")) for event in events] == [
        ("job_status", "running"),
        ("notice", None),
        ("job_status", "done"),
    ]


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (FlashcardError("Provider nicht erreichbar"), "Provider nicht erreichbar"),
        (RuntimeError("geheimer Stacktrace"), UNEXPECTED_ERROR),
    ],
)
def test_errors_mark_job_failed(
    store: JobStore,
    start_worker: Callable[[JobRunner], JobWorker],
    error: Exception,
    message: str,
) -> None:
    """Expected errors keep their message, unexpected ones get a general one.

    Args:
        store: Job store.
        start_worker: Factory for running workers.
        error: Exception raised by the runner.
        message: Expected message for the user.
    """

    def runner(job: Job, report: Reporter, cancel: CancelCheck) -> None:
        """Fail with the given error.

        Args:
            job: Running job.
            report: Event reporter.
            cancel: Cancellation check.
        """
        raise error

    worker = start_worker(runner)
    job_id = submit(store, worker)
    wait_until(lambda: status_of(store, job_id) is JobStatus.FAILED)

    assert store.get(job_id).message == message
    follow_up = submit(store, worker)
    wait_until(lambda: status_of(store, follow_up) is JobStatus.FAILED)


def blocking_runner(started: threading.Event, release: threading.Event) -> JobRunner:
    """Build a runner that waits like the generator and honours cancellation.

    Args:
        started: Set as soon as a job runs.
        release: Lets the job finish normally when set.

    Returns:
        A runner that raises ``GenerationCancelled`` once ``cancel`` is True.
    """

    def runner(job: Job, report: Reporter, cancel: CancelCheck) -> None:
        """Wait for release or cancellation.

        Args:
            job: Running job.
            report: Event reporter.
            cancel: Cancellation check.

        Raises:
            GenerationCancelled: If cancellation was requested.
        """
        started.set()
        while not release.is_set():
            if cancel():
                raise GenerationCancelled("Generation cancelled")
            time.sleep(0.01)

    return runner


def test_cancel_waiting_job(
    store: JobStore, start_worker: Callable[[JobRunner], JobWorker]
) -> None:
    """A waiting job is cancelled at once and never runs.

    Args:
        store: Job store.
        start_worker: Factory for running workers.
    """
    started, release = threading.Event(), threading.Event()
    worker = start_worker(blocking_runner(started, release))
    first = submit(store, worker)
    started.wait(TIMEOUT)
    second = submit(store, worker)

    assert worker.cancel(second)
    assert store.get(second).status is JobStatus.CANCELLED
    assert store.get(second).message == CANCELLED_BY_USER
    release.set()
    wait_until(lambda: status_of(store, first) is JobStatus.DONE)
    assert [event["status"] for event in store.read_events(second)] == ["cancelled"]


def test_cancel_running_job(
    store: JobStore, start_worker: Callable[[JobRunner], JobWorker]
) -> None:
    """A running job stops at its next cancellation check.

    Args:
        store: Job store.
        start_worker: Factory for running workers.
    """
    started, release = threading.Event(), threading.Event()
    worker = start_worker(blocking_runner(started, release))
    job_id = submit(store, worker)
    started.wait(TIMEOUT)

    assert worker.cancel(job_id)
    wait_until(lambda: status_of(store, job_id) is JobStatus.CANCELLED)
    assert store.get(job_id).message == CANCELLED_BY_USER


def test_cancel_finished_or_unknown_job(
    store: JobStore, start_worker: Callable[[JobRunner], JobWorker]
) -> None:
    """Finished and unknown jobs cannot be cancelled.

    Args:
        store: Job store.
        start_worker: Factory for running workers.
    """
    worker = start_worker(lambda job, report, cancel: None)
    job_id = submit(store, worker)
    wait_until(lambda: status_of(store, job_id) is JobStatus.DONE)

    assert not worker.cancel(job_id)
    assert not worker.cancel("0" * 32)


def test_stop_cancels_running_job(store: JobStore) -> None:
    """Stopping the worker cancels the running job with its own message.

    Args:
        store: Job store.
    """
    started, release = threading.Event(), threading.Event()
    worker = JobWorker(store, blocking_runner(started, release), timedelta(days=14))
    worker.start()
    job_id = submit(store, worker)
    started.wait(TIMEOUT)

    worker.stop()

    assert store.get(job_id).status is JobStatus.CANCELLED
    assert store.get(job_id).message == CANCELLED_BY_STOP


def test_start_recovers_unfinished_jobs(store: JobStore) -> None:
    """Jobs left running by a previous process are cancelled on start.

    Args:
        store: Job store.
    """
    job = store.create(io.BytesIO(b"# Titel"), "skript.md", 7)
    store.update(job.id, JobStatus.RUNNING)
    worker = JobWorker(store, lambda job, report, cancel: None, timedelta(days=14))

    worker.start()
    worker.stop()

    assert store.get(job.id).status is JobStatus.CANCELLED
