import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session, sessionmaker

from warroom.db import repo
from warroom.platforms.base import PlatformAdapter

log = logging.getLogger(__name__)

SYNCED_AT_KEY = "players_synced_at"


class PlayerSyncService:
    """Daily player-universe cache (DESIGN.md §3: once per day, never per-lookup)."""

    def __init__(
        self,
        adapter: PlatformAdapter,
        session_factory: sessionmaker[Session],
        max_age_hours: int = 24,
    ) -> None:
        self._adapter = adapter
        self._session_factory = session_factory
        self._max_age = timedelta(hours=max_age_hours)
        self._lock = asyncio.Lock()

    def synced_at(self) -> datetime | None:
        with self._session_factory() as session:
            return repo.get_meta_datetime(session, SYNCED_AT_KEY)

    def is_fresh(self) -> bool:
        synced = self.synced_at()
        return synced is not None and datetime.now(UTC) - synced < self._max_age

    async def ensure_fresh(self, force: bool = False) -> int:
        """Refresh the universe if stale. Returns rows upserted (0 = cache hit)."""
        async with self._lock:
            if not force and self.is_fresh():
                return 0
            log.info("Player universe sync: fetching from %s ...", self._adapter.platform)
            players = await self._adapter.get_players()
            with self._session_factory() as session:
                count = repo.upsert_players(session, players)
                repo.set_meta(
                    session, SYNCED_AT_KEY, datetime.now(UTC).isoformat()
                )
                session.commit()
            log.info("Player universe sync: %d players upserted", count)
            return count
