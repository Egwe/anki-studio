"""Serialize all access to Anki's non-thread-safe local collection (AS-025)."""

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from anki.collection import Collection

Result = TypeVar("Result")
CollectionTask = Callable[[Collection], Result]


class CollectionWorkerStoppedError(RuntimeError):
    """Report an attempted collection access after the worker stopped."""


class CollectionWorkerError(RuntimeError):
    """Report that the worker could not open the local Anki collection."""


@dataclass
class _Request:
    """Hold one synchronous request submitted to the collection thread.

    Attributes:
        task: Function that receives the collection in its owning thread.
        done: Set after a result or exception was recorded.
        result: Return value of ``task``.
        error: Exception raised by ``task``.
    """

    task: CollectionTask[Any]
    done: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: Exception | None = None


class CollectionWorker:
    """Own one collection in a dedicated serial thread.

    The worker opens the collection lazily in its own thread, so routes and
    job runners never receive a ``Collection`` object themselves. Every
    caller waits for its submitted operation, while operations from different
    callers are processed strictly one at a time.

    Attributes:
        path: Absolute collection database path below Anki Studio's data
            directory.
    """

    def __init__(self, path: Path) -> None:
        """Prepare a stopped worker for one collection path.

        Args:
            path: Absolute or relative ``.anki2`` database path. Its parent
                is created only when the first operation opens the collection.
        """
        self.path = path
        self._queue: queue.Queue[_Request | None] = queue.Queue()
        self._lock = threading.Lock()
        self._started = False
        self._stopping = False
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the serial thread without opening the collection yet.

        Returns:
            None.
        """
        with self._lock:
            if self._started:
                return
            self._started = True
            self._thread = threading.Thread(
                target=self._loop, name="anki-studio-collection", daemon=True
            )
            self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the thread and close an opened collection.

        Args:
            timeout: Maximum seconds to wait for an in-progress collection
                operation before returning.

        Returns:
            None.
        """
        with self._lock:
            if not self._started or self._stopping:
                return
            self._stopping = True
            self._queue.put(None)
        if self._thread is not None:
            self._thread.join(timeout)

    def run(self, task: CollectionTask[Result]) -> Result:
        """Run one operation on the collection thread and return its value.

        Args:
            task: Function called with the exclusively owned collection.

        Returns:
            The value returned by ``task``.

        Raises:
            CollectionWorkerStoppedError: If the worker is not running.
            Exception: The exception raised by ``task``.
        """
        request = _Request(task)
        with self._lock:
            if not self._started or self._stopping:
                raise CollectionWorkerStoppedError("Sammlungs-Worker läuft nicht.")
            self._queue.put(request)
        request.done.wait()
        if request.error is not None:
            raise request.error
        return request.result

    def _loop(self) -> None:
        """Open the collection lazily and process requests until stopped.

        Returns:
            None.
        """
        collection: Collection | None = None
        try:
            while (request := self._queue.get()) is not None:
                if collection is None:
                    collection = self._open(request)
                    if collection is None:
                        continue
                self._execute(request, collection)
        finally:
            if collection is not None:
                collection.close()

    def _open(self, request: _Request) -> Collection | None:
        """Open the collection or return its failure to the waiting caller.

        Args:
            request: First queued request that needs the collection.

        Returns:
            The opened collection, or None after recording an opening error
            in ``request``.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            return Collection(str(self.path))
        except Exception:
            request.error = CollectionWorkerError(
                "Lokale Anki-Sammlung kann nicht geöffnet werden."
            )
            request.done.set()
            return None

    @staticmethod
    def _execute(request: _Request, collection: Collection) -> None:
        """Run one task and wake its synchronous caller.

        Args:
            request: Queued request receiving result or exception.
            collection: Collection owned by this worker thread.

        Returns:
            None.
        """
        try:
            request.result = request.task(collection)
        except Exception as error:
            request.error = error
        finally:
            request.done.set()
