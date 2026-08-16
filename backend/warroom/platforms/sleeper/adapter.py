"""Sleeper → normalized DTOs. ALL Sleeper-specific shape knowledge lives here."""

from typing import Any

from warroom.config import Settings
from warroom.platforms.base import PlatformAdapter, PlatformNotFound
from warroom.platforms.models import (
    DraftInfo,
    LeagueInfo,
    PickInfo,
    PlatformUser,
    PlayerInfo,
    ScoringPreset,
    TradedPickInfo,
)
from warroom.platforms.sleeper.client import SleeperClient


def _int_or_none(value: Any) -> int | None:
    # Sleeper is inconsistent: picks carry roster_id as "1", draft maps as int.
    if value is None or value == "":
        return None
    return int(value)


def _scoring_preset(scoring_settings: dict[str, Any]) -> ScoringPreset:
    rec = float(scoring_settings.get("rec", 0) or 0)
    if rec >= 0.75:
        return "ppr"
    if rec >= 0.25:
        return "half_ppr"
    return "standard"


class SleeperAdapter(PlatformAdapter):
    platform = "sleeper"
    poll_interval = 2.0
    traded_picks_interval = 60.0

    def __init__(self, settings: Settings) -> None:
        self.client = SleeperClient(settings.sleeper_base_url)

    async def aclose(self) -> None:
        await self.client.aclose()

    async def resolve_user(self, identifier: str) -> PlatformUser:
        raw = await self.client.get_user(identifier)
        if not raw:
            raise PlatformNotFound(f"Sleeper user {identifier!r} not found")
        return PlatformUser(
            platform=self.platform,
            user_id=str(raw["user_id"]),
            username=raw.get("username"),
            display_name=raw.get("display_name"),
        )

    async def list_leagues(self, user_id: str, season: str) -> list[LeagueInfo]:
        raw_leagues = await self.client.get_user_leagues(user_id, season)
        return [self._league(raw) for raw in raw_leagues]

    def _league(self, raw: dict[str, Any]) -> LeagueInfo:
        settings = raw.get("settings") or {}
        scoring = raw.get("scoring_settings") or {}
        positions: list[str] = raw.get("roster_positions") or []
        roster_slots: dict[str, int] = {}
        for pos in positions:
            roster_slots[pos] = roster_slots.get(pos, 0) + 1
        # settings.type: 0 = redraft, 1 = keeper, 2 = dynasty
        league_type = "dynasty" if settings.get("type") == 2 else "redraft"
        return LeagueInfo(
            platform=self.platform,
            league_id=str(raw["league_id"]),
            name=raw.get("name") or "(unnamed)",
            season=str(raw.get("season") or ""),
            team_count=int(raw.get("total_rosters") or settings.get("num_teams") or 0),
            roster_slots=roster_slots,
            scoring=scoring,
            scoring_preset=_scoring_preset(scoring),
            league_type=league_type,
            raw_settings=settings,
        )

    async def get_league(self, league_id: str) -> LeagueInfo:
        raw = await self.client.get_league(league_id)
        if not raw:
            raise PlatformNotFound(f"Sleeper league {league_id!r} not found")
        return self._league(raw)

    async def list_drafts(self, league_id: str) -> list[DraftInfo]:
        raw_drafts = await self.client.get_league_drafts(league_id)
        return [self._draft(raw) for raw in raw_drafts]

    async def get_draft(self, draft_id: str) -> DraftInfo:
        raw = await self.client.get_draft(draft_id)
        if not raw:
            raise PlatformNotFound(f"Sleeper draft {draft_id!r} not found")
        return self._draft(raw)

    def _draft(self, raw: dict[str, Any]) -> DraftInfo:
        settings = raw.get("settings") or {}
        draft_type = raw.get("type") or "snake"
        if draft_type not in ("snake", "linear", "auction"):
            draft_type = "snake"
        slot_map_raw = raw.get("slot_to_roster_id") or {}
        slot_to_roster = {int(k): _int_or_none(v) for k, v in slot_map_raw.items()}
        draft_order_raw = raw.get("draft_order")
        draft_order = (
            {str(uid): int(slot) for uid, slot in draft_order_raw.items()}
            if draft_order_raw
            else None
        )
        return DraftInfo(
            platform=self.platform,
            draft_id=str(raw["draft_id"]),
            league_id=str(raw["league_id"]) if raw.get("league_id") else None,
            draft_type=draft_type,
            status=raw.get("status") or "pre_draft",
            rounds=int(settings.get("rounds") or 0),
            team_count=int(settings.get("teams") or 0),
            reversal_round=int(settings.get("reversal_round") or 0),
            pick_timer=_int_or_none(settings.get("pick_timer")),
            draft_order=draft_order,
            slot_to_roster=slot_to_roster,
            raw_settings=settings,
        )

    async def get_picks(self, draft_id: str) -> list[PickInfo]:
        raw_picks = await self.client.get_draft_picks(draft_id)
        picks = [
            PickInfo(
                pick_no=int(raw["pick_no"]),
                round=int(raw["round"]),
                draft_slot=int(raw["draft_slot"]),
                platform_player_id=str(raw["player_id"]),
                picked_by=str(raw["picked_by"]) if raw.get("picked_by") else None,
                roster_id=_int_or_none(raw.get("roster_id")),
                is_keeper=bool(raw.get("is_keeper")),
                metadata=raw.get("metadata") or {},
            )
            for raw in raw_picks
        ]
        picks.sort(key=lambda p: p.pick_no)
        return picks

    async def get_traded_picks(self, draft_id: str) -> list[TradedPickInfo]:
        raw_trades = await self.client.get_traded_picks(draft_id)
        return [
            TradedPickInfo(
                season=str(raw.get("season") or ""),
                round=int(raw["round"]),
                # roster_id = the pick's original owner; owner_id = who holds it now
                original_roster_id=int(raw["roster_id"]),
                current_owner_roster_id=int(raw["owner_id"]),
            )
            for raw in raw_trades
        ]

    async def get_players(self) -> list[PlayerInfo]:
        raw_players = await self.client.get_players()
        players: list[PlayerInfo] = []
        for pid, raw in raw_players.items():
            first = raw.get("first_name") or ""
            last = raw.get("last_name") or ""
            name = raw.get("full_name") or f"{first} {last}".strip() or str(pid)
            players.append(
                PlayerInfo(
                    platform_player_id=str(pid),
                    name=name,
                    first_name=first or None,
                    last_name=last or None,
                    position=raw.get("position"),
                    team=raw.get("team"),
                    age=_int_or_none(raw.get("age")),
                    status=raw.get("status"),
                    metadata={
                        "fantasy_positions": raw.get("fantasy_positions"),
                        "injury_status": raw.get("injury_status"),
                        "years_exp": raw.get("years_exp"),
                        "number": raw.get("number"),
                        "search_rank": raw.get("search_rank"),
                    },
                )
            )
        return players
