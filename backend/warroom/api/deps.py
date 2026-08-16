"""FastAPI dependencies — everything hangs off app.state, wired in the lifespan,
so tests can swap in fakes by constructing the app with different state."""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy.orm import Session

from warroom.config import Settings
from warroom.events.broker import EventBroker
from warroom.platforms.base import PlatformAdapter
from warroom.sync.draft_session import SessionManager
from warroom.sync.player_sync import PlayerSyncService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_adapter(request: Request) -> PlatformAdapter:
    return request.app.state.adapter


def get_broker(request: Request) -> EventBroker:
    return request.app.state.broker


def get_session_manager(request: Request) -> SessionManager:
    return request.app.state.sessions


def get_player_sync(request: Request) -> PlayerSyncService:
    return request.app.state.player_sync


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session
