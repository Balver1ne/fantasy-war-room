import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

import warroom
from warroom.api import routes_draft, routes_import, routes_setup, routes_stream
from warroom.config import Settings
from warroom.db.engine import init_db, make_engine, make_session_factory
from warroom.events.broker import EventBroker
from warroom.platforms import get_adapter
from warroom.sync.draft_session import SessionManager
from warroom.sync.player_sync import PlayerSyncService

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    # Use the OS certificate store for TLS. Python's bundled CA list rejects this
    # machine's TLS path (AV/proxy interception is common on Windows); the system
    # store trusts it.
    import truststore

    truststore.inject_into_ssl()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings.db_path)
        init_db(engine)
        session_factory = make_session_factory(engine)
        adapter = get_adapter("sleeper", settings)
        broker = EventBroker()
        player_sync = PlayerSyncService(
            adapter, session_factory, settings.player_sync_max_age_hours
        )
        sessions = SessionManager(adapter, broker, session_factory, settings)

        app.state.settings = settings
        app.state.engine = engine
        app.state.session_factory = session_factory
        app.state.adapter = adapter
        app.state.broker = broker
        app.state.player_sync = player_sync
        app.state.sessions = sessions

        # Warm the player universe without blocking server readiness.
        sync_task = asyncio.create_task(player_sync.ensure_fresh())

        def _report_sync_result(task: asyncio.Task) -> None:
            if not task.cancelled() and task.exception() is not None:
                log.error(
                    "Startup player sync failed: %s — retry via POST /api/players/sync?force=true",
                    task.exception(),
                )

        sync_task.add_done_callback(_report_sync_result)
        log.info("War Room ready on http://%s:%s (debug console at /debug)",
                 settings.host, settings.port)
        try:
            yield
        finally:
            sync_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await sync_task
            await sessions.stop_all()
            await adapter.aclose()
            engine.dispose()

    app = FastAPI(title="War Room", version=warroom.__version__, lifespan=lifespan)
    app.include_router(routes_setup.router)
    app.include_router(routes_draft.router)
    app.include_router(routes_stream.router)
    app.include_router(routes_import.router)

    @app.get("/api/health")
    def health() -> dict:
        player_sync: PlayerSyncService = app.state.player_sync
        sessions: SessionManager = app.state.sessions
        synced_at = player_sync.synced_at()
        return {
            "status": "ok",
            "version": warroom.__version__,
            "players_synced_at": synced_at.isoformat() if synced_at else None,
            "active_sessions": sessions.active_count,
        }

    @app.get("/debug", include_in_schema=False)
    def debug_console() -> FileResponse:
        return FileResponse(STATIC_DIR / "debug.html")

    @app.get("/import", include_in_schema=False)
    def import_console() -> FileResponse:
        return FileResponse(STATIC_DIR / "import.html")

    return app
