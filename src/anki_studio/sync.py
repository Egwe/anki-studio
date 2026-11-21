"""Synchronize Anki Studio's local collection without risking server data."""

import json
import os
import tempfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from anki import sync_pb2
from anki.collection import Collection
from anki_flashcards.apkg import ExportResult
from anki_flashcards.errors import FlashcardError, GenerationCancelled
from anki_flashcards.models import Card
from anki_flashcards.pipeline import write_collection

from anki_studio.collection_worker import CollectionWorker, CollectionWorkerError
from anki_studio.credentials import Credentials
from anki_studio.jobs import Job
from anki_studio.settings import StudioSettings
from anki_studio.worker import CancelCheck, Reporter

SYNC_KIND = "sync"
SYNC_TITLE = "Synchronisieren"
COLLECTION_DIR = "collection"
COLLECTION_FILE = "collection.anki2"
STATE_FILE = "sync.json"


class SyncFailure(FlashcardError):
    """Report a safe, user-visible synchronization failure."""


@dataclass(frozen=True)
class SyncState:
    """Persist non-secret synchronization state.

    Attributes:
        redirect_endpoint: Endpoint supplied by the server after a successful
            sync, or None to use ``studio.yaml``.
        last_synced_at: UTC timestamp of the last successful sync.
        last_result: Machine-readable result of the last attempted sync.
        server_message: Non-secret message returned by the sync server.
        local_changes: Whether Anki Studio has local collection changes that
            were not confirmed by a successful normal sync. A forced complete
            download is refused while this is true.
    """

    redirect_endpoint: str | None = None
    last_synced_at: datetime | None = None
    last_result: str | None = None
    server_message: str | None = None
    local_changes: bool = False


class SyncStateStore:
    """Read and atomically save non-secret sync state beside the collection.

    Attributes:
        path: JSON file below the local collection directory.
    """

    def __init__(self, path: Path) -> None:
        """Remember the state file path.

        Args:
            path: JSON state path below Anki Studio's data directory.
        """
        self.path = path

    def load(self) -> SyncState:
        """Read the saved state or return the safe initial state.

        Returns:
            Saved synchronization state, or the initial no-local-changes
            state when the file does not exist.

        Raises:
            SyncFailure: If an existing state file is malformed.
        """
        if not self.path.exists():
            return SyncState()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return _state_from_data(raw)
        except (OSError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise SyncFailure("Der gespeicherte Sync-Status ist nicht lesbar.") from error

    def save(self, state: SyncState) -> None:
        """Atomically write non-secret synchronization state.

        Args:
            state: State to persist.

        Returns:
            None.

        Raises:
            OSError: If the state cannot be written.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(self.path, _state_data(state))


@dataclass(frozen=True)
class SyncOutcome:
    """Describe one completed sync for the job event log and status page.

    Attributes:
        result: ``no_changes`` or ``full_download`` after a safe sync.
        endpoint: Endpoint used for this sync after a possible redirect.
        server_message: Message returned by the server, if any.
    """

    result: str
    endpoint: str
    server_message: str | None


class SyncService:
    """Login and synchronize through the collection worker (AS-020–AS-025).

    Attributes:
        settings: Application settings containing the configured endpoint.
        credentials: Environment-only sync user name and password.
        worker: Dedicated serial owner of the local collection.
        states: Persistent non-secret synchronization state.
    """

    def __init__(
        self,
        settings: StudioSettings,
        credentials: Credentials,
        worker: CollectionWorker,
        states: SyncStateStore,
    ) -> None:
        """Remember the dependencies of the sync service.

        Args:
            settings: Web application configuration.
            credentials: Secrets loaded from the environment.
            worker: Dedicated worker that owns the collection.
            states: State file storage beside the collection.
        """
        self.settings = settings
        self.credentials = credentials
        self.worker = worker
        self.states = states

    @property
    def configured(self) -> bool:
        """Return whether endpoint and both environment credentials exist.

        Returns:
            True when a sync job can attempt login.
        """
        return bool(
            self.settings.sync_endpoint
            and self.credentials.sync_username
            and self.credentials.sync_password
        )

    def state(self) -> SyncState:
        """Return the current non-secret synchronization state.

        Returns:
            State loaded from disk, or the initial state.
        """
        return self.states.load()

    def sync(self, report: Reporter, cancel: CancelCheck) -> SyncOutcome:
        """Synchronize safely, allowing only a non-destructive full download.

        Args:
            report: Receives user-visible progress notices without secrets.
            cancel: Returns True if the queued sync job was cancelled.

        Returns:
            The successful sync outcome.

        Raises:
            GenerationCancelled: If cancellation was requested before login.
            SyncFailure: If setup, login, server response, or safety checks
                prevent a safe sync.
        """
        if cancel():
            raise GenerationCancelled("Sync abgebrochen")
        state = self._initial_state()
        endpoint = state.redirect_endpoint or self.settings.sync_endpoint
        username = self.credentials.sync_username
        password = self.credentials.sync_password
        if endpoint is None or username is None or password is None:
            raise SyncFailure(
                "Sync ist nicht vollständig eingerichtet: Endpunkt sowie "
                "ANKI_STUDIO_SYNC_USERNAME und ANKI_STUDIO_SYNC_PASSWORD fehlen."
            )
        report({"type": "notice", "text": "Am Sync-Server anmelden …", "level": "info"})
        try:
            outcome = self.worker.run(
                lambda collection: self._sync_collection(
                    collection, state, endpoint, username, password, report
                )
            )
        except (CollectionWorkerError, SyncFailure) as error:
            failure = SyncFailure(str(error))
            self._record_failure(state, str(failure))
            raise failure from error
        self._record_success(state, outcome)
        report({"type": "notice", "text": _success_text(outcome), "level": "info"})
        if outcome.server_message:
            report({"type": "notice", "text": outcome.server_message, "level": "info"})
        return outcome

    def mark_local_changes(self) -> None:
        """Record pending local writes before a collection-changing operation.

        This is called by the future collection-target writer before it changes
        the collection. If the process stops before the following normal sync,
        a later forced full download is refused.

        Returns:
            None.
        """
        state = self._initial_state()
        self.states.save(replace(state, local_changes=True))

    def write_cards(
        self, deck: str, cards: list[Card], report: Reporter, cancel: CancelCheck
    ) -> tuple[ExportResult, SyncOutcome]:
        """Synchronize, write validated cards once, and synchronize again.

        The full sequence runs as one collection-worker request.  It blocks
        another collection operation from appearing between the pre-write
        sync and the Anki change.  The persistent local-change marker is set
        immediately before the write, so a later forced download cannot
        discard an interrupted or unsent write.

        Args:
            deck: Non-empty target deck; ``::`` separates deck levels.
            cards: Validated, locally deduplicated cards selected by a user.
            report: Receives safe progress notices for the job page.
            cancel: Checked before login and before the collection mutation.

        Returns:
            The generator's add/skip result and the final safe sync outcome.

        Raises:
            GenerationCancelled: If cancellation was requested before cards
                were changed.
            SyncFailure: If either synchronization is unsafe or fails.
            FlashcardError: If the generator cannot write into the collection.
        """
        if cancel():
            raise GenerationCancelled("Schreiben abgebrochen")
        state = self._initial_state()
        endpoint, username, password = self._connection(state)
        report(
            {
                "type": "notice",
                "text": "Sammlung vor dem Schreiben abgleichen …",
                "level": "info",
            }
        )
        try:
            result, outcome = self.worker.run(
                lambda collection: self._sync_then_write(
                    collection, state, endpoint, username, password, deck, cards, report, cancel
                )
            )
        except (CollectionWorkerError, SyncFailure) as error:
            failure = SyncFailure(str(error))
            self._record_failure(self._initial_state(), str(failure))
            raise failure from error
        self._record_success(self._initial_state(), outcome)
        report({"type": "notice", "text": _success_text(outcome), "level": "info"})
        if outcome.server_message:
            report({"type": "notice", "text": outcome.server_message, "level": "info"})
        return result, outcome

    def _initial_state(self) -> SyncState:
        """Load state and conservatively classify an untracked collection.

        A collection database without a state file might have been supplied by
        a user. It is therefore marked as locally changed before any server
        response can request a complete download. A missing collection is
        created only by this application and starts disposable.

        Returns:
            Saved state, or a newly persisted conservative initial state.
        """
        if self.states.path.exists():
            return self.states.load()
        state = SyncState(local_changes=self.worker.path.exists())
        self.states.save(state)
        return state

    def _connection(self, state: SyncState) -> tuple[str, str, str]:
        """Return the non-persisted credentials needed for one sync operation.

        Args:
            state: Current non-secret state, including a redirected endpoint.

        Returns:
            Endpoint, user name, and password loaded from the process
            environment.

        Raises:
            SyncFailure: If endpoint or either credential is absent.
        """
        endpoint = state.redirect_endpoint or self.settings.sync_endpoint
        username = self.credentials.sync_username
        password = self.credentials.sync_password
        if endpoint is None or username is None or password is None:
            raise SyncFailure(
                "Sync ist nicht vollständig eingerichtet: Endpunkt sowie "
                "ANKI_STUDIO_SYNC_USERNAME und ANKI_STUDIO_SYNC_PASSWORD fehlen."
            )
        return endpoint, username, password

    def _sync_then_write(
        self,
        collection: Collection,
        state: SyncState,
        endpoint: str,
        username: str,
        password: str,
        deck: str,
        cards: list[Card],
        report: Reporter,
        cancel: CancelCheck,
    ) -> tuple[ExportResult, SyncOutcome]:
        """Perform the two safe sync calls around a collection mutation.

        Args:
            collection: Open collection owned by the collection worker.
            state: State before the pre-write synchronization.
            endpoint: Configured or redirected server endpoint.
            username: Sync user from the environment; never persisted.
            password: Sync password from the environment; never persisted.
            deck: Target deck for the official generator write operation.
            cards: Validated, deduplicated cards to add.
            report: Receives job notices.
            cancel: Checked after the pre-write synchronization.

        Returns:
            Write result and the outcome of the post-write synchronization.

        Raises:
            GenerationCancelled: If cancellation arrives before the write.
            SyncFailure: If either sync cannot complete safely.
            FlashcardError: If the generator rejects the Anki mutation.
        """
        before = self._sync_collection(collection, state, endpoint, username, password, report)
        self._record_success(state, before)
        if cancel():
            raise GenerationCancelled("Schreiben abgebrochen")
        self.mark_local_changes()
        report({"type": "notice", "text": "Karten in die Sammlung schreiben …", "level": "info"})
        result = write_collection(collection, deck, cards)
        report(
            {
                "type": "notice",
                "text": f"{result.added} Karten in Deck „{result.deck}“ geschrieben.",
                "level": "info",
            }
        )
        post_state = self._initial_state()
        report(
            {
                "type": "notice",
                "text": "Sammlung nach dem Schreiben abgleichen …",
                "level": "info",
            }
        )
        return result, self._sync_collection(
            collection, post_state, before.endpoint, username, password, report
        )

    def _sync_collection(
        self,
        collection: Collection,
        state: SyncState,
        endpoint: str,
        username: str,
        password: str,
        report: Reporter,
    ) -> SyncOutcome:
        """Run pylib sync calls while the collection worker exclusively owns it.

        Args:
            collection: Collection owned by the worker thread.
            state: State before this sync, including unsynced-write safety.
            endpoint: Effective configured or redirected endpoint.
            username: Environment-only sync user name.
            password: Environment-only sync password.
            report: Receives progress notices without credentials or hkey.

        Returns:
            Successful safe synchronization outcome.

        Raises:
            SyncFailure: If pylib reports an unsafe or failed synchronization.
        """
        try:
            auth = collection.sync_login(username, password, endpoint)
            report({"type": "notice", "text": "Sammlung abgleichen …", "level": "info"})
            response = collection.sync_collection(auth, sync_media=False)
        except Exception as error:
            raise SyncFailure(
                "Anmeldung oder Abgleich mit dem Sync-Server ist fehlgeschlagen."
            ) from error
        redirected = _redirected_endpoint(response) or endpoint
        if _requires(response, "NO_CHANGES"):
            return SyncOutcome("no_changes", redirected, response.server_message or None)
        if _requires(response, "FULL_DOWNLOAD"):
            return self._full_download(collection, auth, state, redirected, response, report)
        if _requires(response, "FULL_UPLOAD"):
            raise SyncFailure(
                "Der Sync-Server verlangt einen Komplett-Upload. Anki Studio führt ihn "
                "nie automatisch aus, damit keine Serverdaten überschrieben werden."
            )
        if _requires(response, "FULL_SYNC"):
            raise SyncFailure(
                "Der Sync-Server verlangt einen Komplett-Sync. Anki Studio bricht ab, "
                "weil keine sichere Richtung gewählt werden kann."
            )
        raise SyncFailure("Der Sync-Server lieferte einen unerwarteten Synchronisationsstatus.")

    def _full_download(
        self,
        collection: Collection,
        auth: Any,
        state: SyncState,
        endpoint: str,
        response: Any,
        report: Reporter,
    ) -> SyncOutcome:
        """Download a full collection only if no unsent local write exists.

        Args:
            collection: Exclusively owned local collection.
            auth: Temporary pylib login result; never persisted or logged.
            state: State used for the no-local-loss safety decision.
            endpoint: Effective endpoint after any server redirect.
            response: Pylib sync response that requested the download.
            report: Receives progress notices.

        Returns:
            Successful full-download outcome.

        Raises:
            SyncFailure: If local pending writes make a download unsafe, or
                the pylib full-download sequence fails.
        """
        if state.local_changes:
            raise SyncFailure(
                "Der Sync-Server verlangt einen Komplett-Download, aber die lokale "
                "Sammlung enthält noch nicht bestätigte Änderungen. "
                "Anki Studio überschreibt sie nicht."
            )
        report(
            {
                "type": "notice",
                "text": "Leere lokale Sammlung vollständig herunterladen …",
                "level": "info",
            }
        )
        try:
            if endpoint != auth.endpoint:
                auth.endpoint = endpoint
            collection.close_for_full_sync()
            collection.full_upload_or_download(auth=auth, server_usn=None, upload=False)
            collection.reopen(after_full_sync=True)
        except Exception as error:
            raise SyncFailure("Der Komplett-Download der Sammlung ist fehlgeschlagen.") from error
        return SyncOutcome("full_download", endpoint, response.server_message or None)

    def _record_success(self, state: SyncState, outcome: SyncOutcome) -> None:
        """Persist a successful result without secrets or hkey.

        Args:
            state: State from before the successful sync.
            outcome: Successful synchronization result.

        Returns:
            None.
        """
        self.states.save(
            replace(
                state,
                redirect_endpoint=outcome.endpoint,
                last_synced_at=datetime.now(UTC),
                last_result=outcome.result,
                server_message=outcome.server_message,
                local_changes=False,
            )
        )

    def _record_failure(self, state: SyncState, message: str) -> None:
        """Persist a safe failure summary without exposing library details.

        Args:
            state: State from before the failed sync.
            message: Curated user-visible failure message.

        Returns:
            None.
        """
        self.states.save(replace(state, last_result="failed", server_message=message))


class SyncRunner:
    """Run a synchronization as a normal job with live notices.

    Attributes:
        service: Service that owns sync credentials and collection access.
    """

    def __init__(self, service: SyncService) -> None:
        """Remember the sync service.

        Args:
            service: Configured synchronization service.
        """
        self.service = service

    def __call__(self, job: Job, report: Reporter, cancel: CancelCheck) -> None:
        """Synchronize one no-upload job.

        Args:
            job: Queued sync job, retained for worker interface consistency.
            report: Receives job events.
            cancel: Cancellation check before the blocking sync call.

        Returns:
            None.
        """
        del job
        self.service.sync(report, cancel)


def collection_paths(data_dir: Path) -> tuple[Path, Path]:
    """Return the local collection and its non-secret state paths.

    Args:
        data_dir: Application data directory from ``StudioSettings``.

    Returns:
        Collection database path and state JSON path below ``collection/``.
    """
    directory = data_dir / COLLECTION_DIR
    return directory / COLLECTION_FILE, directory / STATE_FILE


def _requires(response: Any, name: str) -> bool:
    """Test one generated pylib ``ChangesRequired`` enum member.

    Args:
        response: Sync response returned by pylib.
        name: Name of the generated enum member.

    Returns:
        Whether the response requests this action.
    """
    required = sync_pb2.SyncCollectionResponse.ChangesRequired.Value(name)
    return response.required == required


def _redirected_endpoint(response: Any) -> str | None:
    """Read an optional endpoint redirect from a pylib sync response.

    Args:
        response: Sync response returned by pylib.

    Returns:
        Redirect endpoint, or None if the field was not supplied.
    """
    return response.new_endpoint if response.HasField("new_endpoint") else None


def _success_text(outcome: SyncOutcome) -> str:
    """Format the final notice of a successful sync.

    Args:
        outcome: Result of a safe sync.

    Returns:
        Short German success message.
    """
    if outcome.result == "full_download":
        return "Komplett-Download abgeschlossen."
    return "Synchronisierung abgeschlossen."


def _state_data(state: SyncState) -> dict[str, Any]:
    """Turn sync state into JSON-safe non-secret data.

    Args:
        state: State to serialize.

    Returns:
        JSON-safe mapping without authentication data.
    """
    return {
        "redirect_endpoint": state.redirect_endpoint,
        "last_synced_at": state.last_synced_at.isoformat() if state.last_synced_at else None,
        "last_result": state.last_result,
        "server_message": state.server_message,
        "local_changes": state.local_changes,
    }


def _state_from_data(data: Any) -> SyncState:
    """Validate persisted non-secret JSON state.

    Args:
        data: Value parsed from the state JSON file.

    Returns:
        Validated immutable state.

    Raises:
        ValueError: If fields have an unexpected type or timestamp format.
    """
    if not isinstance(data, dict):
        raise ValueError("Sync-Status ist kein Objekt.")
    endpoint = _optional_string(data.get("redirect_endpoint"))
    result = _optional_string(data.get("last_result"))
    message = _optional_string(data.get("server_message"))
    local_changes = data.get("local_changes", False)
    if not isinstance(local_changes, bool):
        raise ValueError("Sync-Status enthält keine gültige Änderungsmarkierung.")
    timestamp = data.get("last_synced_at")
    if timestamp is not None and not isinstance(timestamp, str):
        raise ValueError("Sync-Status enthält keinen gültigen Zeitpunkt.")
    synced_at = datetime.fromisoformat(timestamp) if timestamp else None
    return SyncState(endpoint, synced_at, result, message, local_changes)


def _optional_string(value: Any) -> str | None:
    """Validate a nullable non-secret string from persisted JSON.

    Args:
        value: Parsed JSON value.

    Returns:
        The string or None.

    Raises:
        ValueError: If the value is neither a string nor None.
    """
    if value is None or isinstance(value, str):
        return value
    raise ValueError("Sync-Status enthält einen ungültigen Textwert.")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Atomically replace one state JSON file.

    Args:
        path: Destination inside an existing state directory.
        data: JSON-safe non-secret state mapping.

    Returns:
        None.

    Raises:
        OSError: If temporary write or replacement fails.
    """
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False, suffix=".tmp"
    ) as temporary:
        json.dump(data, temporary, ensure_ascii=False, indent=2)
    os.replace(temporary.name, path)
