"""Tests for safe local collection synchronization (AS-020–AS-025)."""

import io
import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from anki import sync_pb2
from anki.collection import Collection
from anki_flashcards.apkg import collection_decks
from anki_flashcards.models import Card, save_cards
from anki_flashcards.pipeline import write_collection
from fastapi.testclient import TestClient

from anki_studio.app import create_app
from anki_studio.card_export import EXPORT_RESULT_FILE
from anki_studio.collection_worker import CollectionWorker, CollectionWorkerError
from anki_studio.credentials import Credentials
from anki_studio.forms import GenerateForm
from anki_studio.generation import CARDS_FILE, job_options
from anki_studio.jobs import JobStatus
from anki_studio.settings import StudioSettings
from anki_studio.sync import SyncFailure, SyncService, SyncState, SyncStateStore, collection_paths
from tests.conftest import PASSWORD, PASSWORD_HASH, SECRET_KEY, SESSION_SECRET, wait_until

SYNC_USER = "studio"
SYNC_PASSWORD = "sync-test-pass"


@pytest.fixture
def sync_server(tmp_path: Path) -> Iterator[str]:
    """Start a private Anki sync server with one test user.

    Args:
        tmp_path: Private folder for server collection data.

    Yields:
        HTTP endpoint bound only to ``127.0.0.1``.
    """
    port = _unused_port()
    environment = os.environ | {
        "SYNC_USER1": f"{SYNC_USER}:{SYNC_PASSWORD}",
        "SYNC_BASE": str(tmp_path / "server"),
        "SYNC_HOST": "127.0.0.1",
        "SYNC_PORT": str(port),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "anki.syncserver"],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    endpoint = f"http://127.0.0.1:{port}/"
    try:
        _wait_for_server(port, process)
        yield endpoint
    finally:
        process.terminate()
        process.wait(timeout=10)


def _unused_port() -> int:
    """Reserve an ephemeral loopback port long enough to learn its number.

    Returns:
        Port number that was free at the time of selection.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_server(port: int, process: subprocess.Popen[bytes]) -> None:
    """Wait until a loopback sync server accepts TCP connections.

    Args:
        port: TCP port selected for the test server.
        process: Sync-server process, used to detect early failure.

    Returns:
        None.

    Raises:
        RuntimeError: If the process exits or does not listen in time.
    """
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Lokaler Anki-Sync-Server konnte nicht starten.")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("Lokaler Anki-Sync-Server antwortet nicht rechtzeitig.")


def _seed_server(tmp_path: Path, endpoint: str) -> None:
    """Create one remote note through a disposable desktop-style client.

    The test fixture performs the initial full upload solely to prepare a
    server fixture. Anki Studio's production service is never used for a
    full upload.

    Args:
        tmp_path: Test folder receiving the temporary client collection.
        endpoint: Loopback sync-server endpoint.

    Returns:
        None.
    """
    collection = Collection(str(tmp_path / "desktop.anki2"))
    try:
        write_collection(
            collection,
            "Elektrotechnik",
            [Card(front="Was ist Ohm?", back="Einheit des Widerstands")],
        )
        auth = collection.sync_login(SYNC_USER, SYNC_PASSWORD, endpoint)
        response = collection.sync_collection(auth, sync_media=False)
        assert response.required == response.ChangesRequired.FULL_UPLOAD
        collection.close_for_full_sync()
        collection.full_upload_or_download(auth=auth, server_usn=None, upload=True)
        collection.reopen(after_full_sync=True)
    finally:
        collection.close()


def _service(tmp_path: Path, endpoint: str) -> tuple[SyncService, CollectionWorker, SyncStateStore]:
    """Build a sync service with a private worker and state file.

    Args:
        tmp_path: Test folder for the local Anki Studio collection.
        endpoint: Loopback sync-server endpoint.

    Returns:
        Service, started collection worker, and its state storage.
    """
    settings = StudioSettings(data_dir=tmp_path / "studio", sync_endpoint=endpoint)
    collection_path, state_path = collection_paths(settings.data_dir)
    worker = CollectionWorker(collection_path)
    worker.start()
    credentials = Credentials(
        None,
        "x" * 32,
        secret_key=None,
        sync_username=SYNC_USER,
        sync_password=SYNC_PASSWORD,
    )
    states = SyncStateStore(state_path)
    return SyncService(settings, credentials, worker, states), worker, states


@pytest.mark.sync
def test_first_sync_downloads_the_server_collection_without_secrets(
    tmp_path: Path, sync_server: str
) -> None:
    """An empty Studio copy uses only the safe full-download sequence.

    Args:
        tmp_path: Temporary folders for remote and local collections.
        sync_server: Private loopback endpoint.
    """
    _seed_server(tmp_path, sync_server)
    service, worker, states = _service(tmp_path, sync_server)
    events: list[dict[str, object]] = []
    try:
        outcome = service.sync(events.append, lambda: False)
        decks = worker.run(collection_decks)
    finally:
        worker.stop()

    state_text = states.path.read_text(encoding="utf-8")
    assert outcome.result == "full_download"
    assert any(deck["name"] == "Elektrotechnik" and deck["cards"] == 1 for deck in decks)
    assert "Komplett-Download abgeschlossen" in str(events)
    assert SYNC_USER not in state_text
    assert SYNC_PASSWORD not in state_text
    assert "hkey" not in state_text


@pytest.mark.sync
def test_full_download_refuses_a_collection_with_pending_local_changes(
    tmp_path: Path, sync_server: str
) -> None:
    """A server request cannot overwrite a locally marked pending write.

    Args:
        tmp_path: Temporary folders for remote and local collections.
        sync_server: Private loopback endpoint.
    """
    _seed_server(tmp_path, sync_server)
    service, worker, states = _service(tmp_path, sync_server)
    states.save(SyncState(local_changes=True))
    try:
        with pytest.raises(SyncFailure, match="nicht bestätigte Änderungen"):
            service.sync(lambda event: None, lambda: False)
    finally:
        worker.stop()

    assert states.load().local_changes is True
    assert states.load().last_result == "failed"


@pytest.mark.sync
def test_write_cards_syncs_before_and_after_and_reaches_the_server(
    tmp_path: Path, sync_server: str
) -> None:
    """A collection write is surrounded by safe normal syncs.

    Args:
        tmp_path: Temporary server and client data folders.
        sync_server: Private loopback endpoint of the test sync server.
    """
    _seed_server(tmp_path, sync_server)
    service, worker, states = _service(tmp_path / "writer", sync_server)
    events: list[dict[str, object]] = []
    try:
        service.sync(events.append, lambda: False)
        result, outcome = service.write_cards(
            "Elektrotechnik",
            [Card(front="Was ist Leistung?", back="Energie pro Zeit")],
            events.append,
            lambda: False,
        )
        local_decks = worker.run(collection_decks)
    finally:
        worker.stop()

    reader, reader_worker, _ = _service(tmp_path / "reader", sync_server)
    try:
        reader.sync(lambda event: None, lambda: False)
        remote_decks = reader_worker.run(collection_decks)
    finally:
        reader_worker.stop()

    assert (result.added, result.skipped) == (1, 0)
    assert outcome.result == "no_changes"
    assert states.load().local_changes is False
    assert any(deck["cards"] == 2 for deck in local_decks if deck["name"] == "Elektrotechnik")
    assert any(deck["cards"] == 2 for deck in remote_decks if deck["name"] == "Elektrotechnik")
    notices = [str(event.get("text")) for event in events if event.get("type") == "notice"]
    assert "Sammlung vor dem Schreiben abgleichen …" in notices
    assert "Sammlung nach dem Schreiben abgleichen …" in notices


class _FullUploadCollection:
    """Minimal pylib boundary that asks Anki Studio for a full upload.

    Attributes:
        full_upload_called: Whether the forbidden pylib method was reached.
    """

    def __init__(self) -> None:
        """Prepare a response that demands the forbidden operation."""
        self.full_upload_called = False

    def sync_login(self, username: str, password: str, endpoint: str) -> sync_pb2.SyncAuth:
        """Return temporary auth without storing the supplied test values.

        Args:
            username: Test sync user name.
            password: Test sync password.
            endpoint: Test sync endpoint.

        Returns:
            Temporary generated sync auth.
        """
        del username, password
        return sync_pb2.SyncAuth(endpoint=endpoint)

    def sync_collection(
        self, auth: sync_pb2.SyncAuth, sync_media: bool
    ) -> sync_pb2.SyncCollectionResponse:
        """Return a full-upload request like pylib would.

        Args:
            auth: Temporary auth, unused by this fake.
            sync_media: Whether media would be synchronized, always false.

        Returns:
            Generated response requesting ``FULL_UPLOAD``.
        """
        del auth, sync_media
        return sync_pb2.SyncCollectionResponse(
            required=sync_pb2.SyncCollectionResponse.ChangesRequired.FULL_UPLOAD
        )

    def full_upload_or_download(self, **kwargs: object) -> None:
        """Record an unexpected forbidden upload invocation.

        Args:
            **kwargs: Pylib full-sync arguments, unused in the fake.

        Returns:
            None.
        """
        del kwargs
        self.full_upload_called = True


def test_sync_never_runs_a_server_requested_full_upload(tmp_path: Path) -> None:
    """A ``FULL_UPLOAD`` reply cannot call pylib's destructive upload method.

    Args:
        tmp_path: Temporary folder for the private sync service state.
    """
    endpoint = "http://sync.example/"
    service, worker, _ = _service(tmp_path, endpoint)
    collection = _FullUploadCollection()
    try:
        with pytest.raises(SyncFailure, match="Komplett-Upload"):
            service._sync_collection(
                collection,
                SyncState(),
                endpoint,
                SYNC_USER,
                SYNC_PASSWORD,
                lambda event: None,
            )
    finally:
        worker.stop()

    assert collection.full_upload_called is False


def test_collection_worker_runs_all_actions_on_its_own_thread(tmp_path: Path) -> None:
    """Collection work never runs in the route or test caller thread.

    Args:
        tmp_path: Temporary directory for the collection database.
    """
    worker = CollectionWorker(tmp_path / "collection" / "collection.anki2")
    worker.start()
    try:
        first = worker.run(lambda collection: (id(collection), threading.get_ident()))
        second = worker.run(lambda collection: (id(collection), threading.get_ident()))
    finally:
        worker.stop()

    assert first == second
    assert first[1] != threading.get_ident()


def test_collection_worker_returns_an_opening_failure_to_the_caller(tmp_path: Path) -> None:
    """An unreadable collection path does not leave a request waiting forever.

    Args:
        tmp_path: Temporary directory with a file used as an invalid parent.
    """
    invalid_parent = tmp_path / "not-a-directory"
    invalid_parent.write_text("file", encoding="utf-8")
    worker = CollectionWorker(invalid_parent / "collection.anki2")
    worker.start()
    try:
        with pytest.raises(CollectionWorkerError, match="kann nicht geöffnet werden"):
            worker.run(lambda collection: collection)
    finally:
        worker.stop()


def test_sync_page_explains_missing_setup_without_creating_a_job(auth_client: TestClient) -> None:
    """The sync page never exposes or invents missing environment secrets.

    Args:
        auth_client: Logged-in client without sync configuration.
    """
    page = auth_client.get("/sync")
    submission = auth_client.post("/sync")

    assert page.status_code == 200
    assert "Endpunkt" in page.text and "fehlt" in page.text
    assert submission.status_code == 400
    assert auth_client.app.state.jobs.list_jobs() == []


@pytest.mark.sync
def test_sync_page_queues_a_live_job_and_never_renders_the_password(
    tmp_path: Path, studio_settings: StudioSettings, sync_server: str
) -> None:
    """Configured sync runs as a job and its page omits the password.

    Args:
        tmp_path: Temporary test directory for the remote seed collection.
        studio_settings: Base application settings with private data folder.
        sync_server: Private loopback endpoint.
    """
    _seed_server(tmp_path, sync_server)
    settings = studio_settings.model_copy(update={"sync_endpoint": sync_server})
    credentials = Credentials(
        PASSWORD_HASH,
        SESSION_SECRET,
        secret_key=SECRET_KEY,
        sync_username=SYNC_USER,
        sync_password=SYNC_PASSWORD,
    )
    with TestClient(create_app(settings, credentials)) as client:
        login = client.post("/login", data={"password": PASSWORD}, follow_redirects=False)
        response = client.post("/sync", follow_redirects=False)
        job_id = response.headers["location"].rsplit("/", 1)[-1]
        wait_until(lambda: client.app.state.jobs.get(job_id).status is JobStatus.DONE)
        job_page = client.get(f"/jobs/{job_id}").text
        status = client.get("/sync").text

    assert login.status_code == 303
    assert response.status_code == 303
    assert "Synchronisierung abgeschlossen" in job_page
    assert "full_download" in status
    assert SYNC_PASSWORD not in job_page
    assert SYNC_PASSWORD not in status


@pytest.mark.sync
def test_collection_target_queues_a_review_write_job(
    tmp_path: Path, studio_settings: StudioSettings, sync_server: str
) -> None:
    """A collection-target review reserves cards and shows its final result.

    Args:
        tmp_path: Temporary remote collection data.
        studio_settings: Private application paths and generator configuration.
        sync_server: Private loopback endpoint of the temporary server.
    """
    _seed_server(tmp_path, sync_server)
    settings = studio_settings.model_copy(update={"sync_endpoint": sync_server})
    credentials = Credentials(
        PASSWORD_HASH,
        SESSION_SECRET,
        secret_key=SECRET_KEY,
        sync_username=SYNC_USER,
        sync_password=SYNC_PASSWORD,
    )
    with TestClient(create_app(settings, credentials)) as client:
        client.post("/login", data={"password": PASSWORD}, follow_redirects=False)
        store = client.app.state.jobs
        job = store.create(
            io.BytesIO(b"# Leistung"),
            "leistung.md",
            10,
            job_options(
                GenerateForm.model_validate({"target": "collection", "deck": "Elektrotechnik"})
            ),
        )
        save_cards(
            store.job_dir(job.id) / CARDS_FILE,
            [Card(front="Was ist Leistung?", back="Energie pro Zeit")],
            deck="Elektrotechnik",
        )
        source = store.update(job.id, JobStatus.DONE)

        response = client.post(f"/jobs/{source.id}/write", data={"deck": "Elektrotechnik"})
        write_id = response.url.path.rsplit("/", 1)[-1]
        wait_until(lambda: store.get(write_id).status is JobStatus.DONE)
        source_page = client.get(f"/jobs/{source.id}")

    assert response.status_code == 200
    assert "synchronisierte Sammlung" in source_page.text
    assert "1 neue Karten geschrieben" in source_page.text
    assert "APKG herunterladen" not in source_page.text


@pytest.mark.sync
def test_card_json_export_can_write_to_the_synchronized_collection(
    tmp_path: Path, studio_settings: StudioSettings, sync_server: str
) -> None:
    """The export form uses the same safe collection target as reviewed cards.

    Args:
        tmp_path: Temporary remote collection data.
        studio_settings: Private application paths and generator configuration.
        sync_server: Private loopback endpoint of the temporary server.
    """
    _seed_server(tmp_path, sync_server)
    settings = studio_settings.model_copy(update={"sync_endpoint": sync_server})
    credentials = Credentials(
        PASSWORD_HASH,
        SESSION_SECRET,
        secret_key=SECRET_KEY,
        sync_username=SYNC_USER,
        sync_password=SYNC_PASSWORD,
    )
    payload = json.dumps(
        {
            "schema_version": 1,
            "deck": "ignored",
            "cards": [{"front": "Was ist Strom?", "back": "Ladung pro Zeit"}],
        }
    ).encode()
    with TestClient(create_app(settings, credentials)) as client:
        client.post("/login", data={"password": PASSWORD}, follow_redirects=False)
        response = client.post(
            "/export",
            data={"target": "collection", "deck": "Elektrotechnik"},
            files={"cards": ("karten.cards.json", io.BytesIO(payload), "application/json")},
            follow_redirects=False,
        )
        job_id = response.headers["location"].rsplit("/", 1)[-1]
        store = client.app.state.jobs
        wait_until(lambda: store.get(job_id).status is JobStatus.DONE)
        result_path = store.job_dir(job_id) / EXPORT_RESULT_FILE
        result = json.loads(result_path.read_text(encoding="utf-8"))
        page = client.get(f"/jobs/{job_id}")
        download = client.get(f"/export/jobs/{job_id}/file")

    assert response.status_code == 303
    assert result["target"] == "collection"
    assert result["added"] == 1
    assert "synchronisierte Sammlung geschrieben" in page.text
    assert download.status_code == 404
