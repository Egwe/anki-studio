"""Run jobs one after another in a single background thread (AS-032).

One GPU and one user: exactly one job runs at a time, further jobs wait in
a queue. What a job does is decided by the injected runner; the worker
only handles order, status, events, and cancellation.
"""

import logging
import queue
import threading
from collections.abc import Callable
from datetime import timedelta
from functools import partial
from typing import Any

from anki_flashcards.errors import FlashcardError, GenerationCancelled

from anki_studio.jobs import Job, JobStatus, JobStore

Reporter = Callable[[dict[str, Any]], None]
CancelCheck = Callable[[], bool]
JobRunner = Callable[[Job, Reporter, CancelCheck], None]

CANCELLED_BY_USER = "Vom Benutzer abgebrochen."
CANCELLED_BY_STOP = "Beim Beenden von Anki Studio abgebrochen."
UNEXPECTED_ERROR = "Unerwarteter Fehler; Details stehen im Protokoll des Dienstes."

logger = logging.getLogger(__name__)


class JobWorker:
    """Queue jobs and run them in one daemon thread.

    Attributes:
        store: Job store holding state and events.
        runner: Function that performs a job; it receives the job, a
            reporter for JSON events, and a cancellation check.
        retention: Age after which finished jobs are deleted.
    """

    def __init__(self, store: JobStore, runner: JobRunner, retention: timedelta) -> None:
        """Prepare the worker without starting the thread.

        Args:
            store: Job store holding state and events.
            runner: Function that performs one job.
            retention: Age after which finished jobs are deleted.
        """
        self.store = store
        self.runner = runner
        self.retention = retention
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._cancel: dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._stopping = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Clean up after a restart and start the worker thread.

        Unfinished jobs from a previous run are marked as cancelled and
        expired jobs are deleted before the thread starts.

        Returns:
            None.
        """
        self.store.recover()
        self.store.remove_expired(self.retention)
        self._thread = threading.Thread(target=self._loop, name="anki-studio-jobs", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Ask the running job to stop and end the thread.

        Args:
            timeout: Seconds to wait for the thread; a provider request in
                progress is not interrupted, so the thread may outlive this.

        Returns:
            None.
        """
        with self._lock:
            self._stopping = True
            for event in self._cancel.values():
                event.set()
        self._queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout)

    def submit(self, job: Job) -> None:
        """Put a queued job at the end of the queue.

        Args:
            job: Job with status ``queued``.

        Returns:
            None.
        """
        with self._lock:
            self._cancel[job.id] = threading.Event()
        self._queue.put(job.id)

    def cancel(self, job_id: str) -> bool:
        """Cancel a waiting job at once or ask a running job to stop.

        A running job stops at the generator's next cancellation check; a
        provider request in progress finishes first.

        Args:
            job_id: Identifier of the job.

        Returns:
            True if the job was waiting or running, False if it is unknown or
            already finished.
        """
        with self._lock:
            job = self.store.get(job_id)
            if job is None or job.status.finished:
                return False
            if job_id in self._cancel:
                self._cancel[job_id].set()
            if job.status is JobStatus.QUEUED:
                self._set_status(job_id, JobStatus.CANCELLED, CANCELLED_BY_USER)
        return True

    def _loop(self) -> None:
        """Take job identifiers from the queue until ``None`` arrives.

        Returns:
            None.
        """
        while (job_id := self._queue.get()) is not None:
            self._run(job_id)

    def _run(self, job_id: str) -> None:
        """Run one job if it is still waiting and record its outcome.

        Args:
            job_id: Identifier taken from the queue.

        Returns:
            None.
        """
        job = self._claim(job_id)
        if job is None:
            return
        cancel_event = self._cancel[job_id]
        status, message = self._execute(job, cancel_event.is_set)
        with self._lock:
            if status is JobStatus.CANCELLED and self._stopping:
                message = CANCELLED_BY_STOP
            self._set_status(job_id, status, message)
            self._cancel.pop(job_id, None)
        self.store.remove_expired(self.retention)

    def _claim(self, job_id: str) -> Job | None:
        """Switch a waiting job to running.

        Args:
            job_id: Identifier taken from the queue.

        Returns:
            The running job, or None if it was cancelled or removed meanwhile.
        """
        with self._lock:
            job = self.store.get(job_id)
            if job is None or job.status is not JobStatus.QUEUED or self._stopping:
                return None
            self._set_status(job_id, JobStatus.RUNNING)
            return self.store.get(job_id)

    def _execute(self, job: Job, cancel: CancelCheck) -> tuple[JobStatus, str | None]:
        """Call the runner and translate its outcome into a final status.

        The worker thread is the boundary between the generator and the
        application: an unexpected exception is logged with traceback and
        reported as a general failure, so the thread keeps working.

        Args:
            job: The running job.
            cancel: Cancellation check passed to the runner.

        Returns:
            The final status and the message for the user, if any.
        """
        report = partial(self.store.append_event, job.id)
        try:
            self.runner(job, report, cancel)
        except GenerationCancelled:
            return JobStatus.CANCELLED, CANCELLED_BY_USER
        except FlashcardError as error:
            return JobStatus.FAILED, str(error)
        except Exception:
            logger.exception("Job %s ist unerwartet fehlgeschlagen", job.id)
            return JobStatus.FAILED, UNEXPECTED_ERROR
        return JobStatus.DONE, None

    def _set_status(self, job_id: str, status: JobStatus, message: str | None = None) -> None:
        """Store a status and append it as ``job_status`` event.

        Args:
            job_id: Identifier of the job.
            status: New status.
            message: Message for the user, or None.

        Returns:
            None.
        """
        self.store.update(job_id, status, message)
        self.store.append_event(
            job_id, {"type": "job_status", "status": status.value, "message": message}
        )
