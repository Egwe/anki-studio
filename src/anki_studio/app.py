"""Create the FastAPI application of Anki Studio."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

from anki_flashcards.errors import FlashcardError
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from anki_studio.auth import SESSION_COOKIE, SESSION_MAX_AGE, LoginRequiredMiddleware
from anki_studio.card_export import EXPORT_KIND, ExportRunner
from anki_studio.collection_worker import CollectionWorker
from anki_studio.collection_write import COLLECTION_WRITE_KIND, CollectionWriteRunner
from anki_studio.credentials import SESSION_SECRET_ENV, Credentials, load_credentials
from anki_studio.decks import DECKS_KIND, DecksRunner
from anki_studio.generation import GENERATE_KIND, GenerationRunner, KindRunner
from anki_studio.generator_config import ensure_generator_config
from anki_studio.headers import SecurityHeadersMiddleware
from anki_studio.hosts import HostCheckMiddleware
from anki_studio.jobs import JobStore
from anki_studio.limits import BodyLimitMiddleware
from anki_studio.models_task import MODELS_KIND, ModelsRunner
from anki_studio.routes import (
    access,
    config,
    decks,
    export,
    generate,
    jobs,
    keys,
    language,
    login,
    models,
    pages,
    review,
    structured,
)
from anki_studio.routes import sync as sync_routes
from anki_studio.secret_store import STORE_FILE, SecretStore, SecretStoreError
from anki_studio.settings import StudioSettings
from anki_studio.sync import SYNC_KIND, SyncRunner, SyncService, SyncStateStore, collection_paths
from anki_studio.templating import STATIC_DIR, create_templates
from anki_studio.worker import JobWorker

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the job worker with the application and stop it afterwards.

    On start, jobs left unfinished by a previous process are marked as
    cancelled and expired jobs are deleted (AS-032).

    Args:
        app: The application; ``app.state.settings`` must be set.

    Yields:
        Control to the running application; ``app.state.jobs`` and
        ``app.state.worker`` are available meanwhile.
    """
    settings: StudioSettings = app.state.settings
    _ensure_generator_config(settings)
    _open_secret_store(app)
    store = JobStore(settings.data_dir / "jobs")
    collection_path, state_path = collection_paths(settings.data_dir)
    collection_worker = CollectionWorker(collection_path)
    collection_worker.start()
    sync_service = SyncService(
        settings, app.state.credentials, collection_worker, SyncStateStore(state_path)
    )
    runner = KindRunner(
        {
            GENERATE_KIND: GenerationRunner(
                store, settings.generator_path, collection_worker, sync_service
            ),
            MODELS_KIND: ModelsRunner(settings.generator_path),
            DECKS_KIND: DecksRunner(store),
            EXPORT_KIND: ExportRunner(store, settings.generator_path, sync_service),
            SYNC_KIND: SyncRunner(sync_service),
            COLLECTION_WRITE_KIND: CollectionWriteRunner(store, sync_service),
        }
    )
    worker = JobWorker(store, runner, timedelta(days=settings.job_retention_days))
    worker.start()
    app.state.jobs = store
    app.state.worker = worker
    app.state.collection_worker = collection_worker
    app.state.sync_service = sync_service
    try:
        yield
    finally:
        worker.stop()
        collection_worker.stop()


def _ensure_generator_config(settings: StudioSettings) -> None:
    """Create the generator YAML or add missing standard profiles at start.

    A broken or unwritable file does not stop the application; the
    generation page then explains the problem.

    Args:
        settings: Application settings.

    Returns:
        None.
    """
    path = settings.generator_path
    try:
        added = ensure_generator_config(path, settings.data_dir / "models")
    except (FlashcardError, OSError) as error:
        logger.warning("Generator-Konfiguration %s nicht ergänzt: %s", path, error)
        return
    if added:
        logger.info("Generator-Konfiguration %s: Profile ergänzt: %s", path, ", ".join(added))


def _open_secret_store(app: FastAPI) -> None:
    """Open the encrypted key store and apply its keys to the environment.

    A file that cannot be decrypted does not stop the application; the key
    page shows the problem (AS-035).

    Args:
        app: The application; sets ``app.state.secrets`` and
            ``app.state.secrets_error``.

    Returns:
        None.
    """
    settings: StudioSettings = app.state.settings
    store = SecretStore(settings.data_dir / STORE_FILE, app.state.credentials.secret_key)
    app.state.secrets = store
    app.state.secrets_error = None
    try:
        store.apply()
    except SecretStoreError as error:
        logger.warning("Gespeicherte API-Schlüssel nicht geladen: %s", error)
        app.state.secrets_error = str(error)


def create_app(
    settings: StudioSettings | None = None, credentials: Credentials | None = None
) -> FastAPI:
    """Build the web application with routes, static files, and middleware.

    Middleware from the outside in: security headers, host check, body size
    limit, signed session cookie, login requirement. The interactive API
    documentation is disabled: it would load scripts from a CDN.

    Args:
        settings: Validated settings; None uses the built-in defaults.
        credentials: Login secrets; None reads them from ``os.environ``.

    Returns:
        A configured application; ``app.state`` holds ``settings``,
        ``credentials``, ``templates``, and ``http_transport`` (None for the
        network; tests set a mock), and while running ``jobs``, ``worker``,
        ``collection_worker``, ``sync_service``, and ``secrets``.

    Raises:
        CredentialsError: If ``credentials`` is None and the environment
            holds an invalid password hash or session key.
    """
    settings = settings or StudioSettings()
    credentials = credentials or load_credentials(os.environ)
    if credentials.temporary_secret:
        logger.warning(
            "%s fehlt: zufälliger Session-Schlüssel, Anmeldungen enden mit einem Neustart.",
            SESSION_SECRET_ENV,
        )
    app = FastAPI(
        title="Anki Studio", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.settings = settings
    app.state.credentials = credentials
    app.state.templates = create_templates()
    app.state.http_transport = None
    app.state.request_restart = _no_restart
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    for module in (
        access,
        login,
        language,
        pages,
        generate,
        jobs,
        keys,
        models,
        review,
        config,
        structured,
        decks,
        export,
        sync_routes,
    ):
        app.include_router(module.router)
    app.add_middleware(LoginRequiredMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=credentials.session_secret,
        session_cookie=SESSION_COOKIE,
        max_age=SESSION_MAX_AGE,
        same_site="strict",
    )
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(HostCheckMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(SecurityHeadersMiddleware)
    return app


def _no_restart() -> None:
    """Keep in-process test applications alive after a settings change.

    The command-line server replaces this callback with a controlled SIGTERM;
    tests and embedded app users deliberately do not restart their process.

    Returns:
        None.
    """
