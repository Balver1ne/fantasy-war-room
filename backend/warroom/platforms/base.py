from abc import ABC, abstractmethod
from typing import ClassVar

from warroom.platforms.models import (
    DraftInfo,
    LeagueInfo,
    PickInfo,
    PlatformUser,
    PlayerInfo,
    TradedPickInfo,
)


class PlatformNotFound(Exception):
    """Entity does not exist on the platform (Sleeper returns HTTP 200 + null body)."""


class PlatformAdapter(ABC):
    """Vendor boundary (DESIGN.md §3).

    The recommendation engine, data model, and UI consume only the normalized DTOs
    returned here; no platform-specific logic may exist outside an adapter package.
    Each adapter owns its polling cadence and rate-limit posture via the class attrs.
    """

    platform: ClassVar[str]
    poll_interval: ClassVar[float]
    traded_picks_interval: ClassVar[float]

    @abstractmethod
    async def resolve_user(self, identifier: str) -> PlatformUser: ...

    @abstractmethod
    async def list_leagues(self, user_id: str, season: str) -> list[LeagueInfo]: ...

    @abstractmethod
    async def get_league(self, league_id: str) -> LeagueInfo: ...

    @abstractmethod
    async def list_drafts(self, league_id: str) -> list[DraftInfo]: ...

    @abstractmethod
    async def get_draft(self, draft_id: str) -> DraftInfo: ...

    @abstractmethod
    async def get_picks(self, draft_id: str) -> list[PickInfo]: ...

    @abstractmethod
    async def get_traded_picks(self, draft_id: str) -> list[TradedPickInfo]: ...

    @abstractmethod
    async def get_players(self) -> list[PlayerInfo]:
        """Full player universe. Callers must go through PlayerSyncService's cache
        policy — never call this per-lookup (the Sleeper payload is ~5 MB)."""
        ...

    @abstractmethod
    async def aclose(self) -> None: ...
