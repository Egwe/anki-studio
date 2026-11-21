"""Write reviewed cards into the synchronized collection as a job (AS-002, AS-006)."""

from anki_flashcards.errors import FlashcardError

from anki_studio.jobs import Job, JobStatus, JobStore
from anki_studio.review import (
    collection_result,
    finish_collection_write,
    release_collection_write,
    reserved_collection_cards,
)
from anki_studio.sync import SyncService
from anki_studio.worker import CancelCheck, Reporter

COLLECTION_WRITE_KIND = "collection_write"
COLLECTION_WRITE_TITLE = "Karten in Sammlung schreiben"


class CollectionWriteRunner:
    """Synchronize around a one-time reviewed-card collection write.

    Attributes:
        store: Job folders containing the source review and write task.
        sync: Service owning credentials and serial collection access.
    """

    def __init__(self, store: JobStore, sync: SyncService) -> None:
        """Remember the job storage and safe collection service.

        Args:
            store: Job store containing source reviews and task jobs.
            sync: Sync service that performs pre-write and post-write syncs.
        """
        self.store = store
        self.sync = sync

    def __call__(self, job: Job, report: Reporter, cancel: CancelCheck) -> None:
        """Write the review reserved for one collection-write task.

        Args:
            job: Running no-upload task with ``source_job_id`` in its options.
            report: Receives user-visible job notices.
            cancel: Checked by the synchronization service before mutation.

        Returns:
            None.

        Raises:
            FlashcardError: If the source review is unavailable or either
                synchronization or official collection write fails.
        """
        source = self._source_job(job)
        try:
            deck, cards = reserved_collection_cards(self.store, source, job.id)
            result, outcome = self.sync.write_cards(deck, cards, report, cancel)
            finish_collection_write(
                self.store, source, job.id, collection_result(result, outcome.result)
            )
            report(
                {
                    "type": "notice",
                    "text": "Kartenprüfung als geschrieben markiert.",
                    "level": "info",
                }
            )
        except BaseException:
            # A failed, cancelled, or unexpectedly interrupted task must not
            # permanently lock the user's review. The collection state remains
            # conservatively marked as locally changed by SyncService.
            release_collection_write(self.store, source, job.id)
            raise

    def _source_job(self, job: Job) -> Job:
        """Load the finished generation job whose review this task owns.

        Args:
            job: Collection-write task with a source-job option.

        Returns:
            The completed source generation job.

        Raises:
            FlashcardError: If the source identifier is missing or no longer
                refers to a completed generation job.
        """
        source_id = job.options.get("source_job_id")
        source = self.store.get(source_id) if isinstance(source_id, str) else None
        if source is None or source.status is not JobStatus.DONE:
            raise FlashcardError("Die zugehörige Kartenprüfung ist nicht verfügbar.")
        return source
