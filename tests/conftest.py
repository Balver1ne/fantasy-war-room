import json
from pathlib import Path

import pytest
from warroom.config import Settings
from warroom.db.engine import init_db, make_engine, make_session_factory
from warroom.events.broker import Event, EventBroker
from warroom.platforms.base import PlatformAdapter, PlatformNotFound
from warroom.platforms.models import (
    DraftInfo,
    LeagueInfo,
    PickInfo,
    PlatformUser,
    PlayerInfo,
    TradedPickInfo,
)

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "sleeper"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        db_path=tmp_path / "test.db",
        sleeper_base_url="http://sleeper.test/v1",
        _env_file=None,
    )


@pytest.fixture
def session_factory(settings):
    engine = make_engine(settings.db_path)
    init_db(engine)
    yield make_session_factory(engine)
    engine.dispose()


class CapturingBroker(EventBroker):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[Event] = []

    def publish(self, event: Event) -> None:
        self.events.append(event)
        super().publish(event)

    def of_type(self, type_: str) -> list[Event]:
        return [e for e in self.events if e.type == type_]


@pytest.fixture
def broker() -> CapturingBroker:
    return CapturingBroker()


def sample_players() -> list[PlayerInfo]:
    players = []
    for pid, raw in load_fixture("players_sample.json").items():
        first = raw.get("first_name") or ""
        last = raw.get("last_name") or ""
        players.append(
            PlayerInfo(
                platform_player_id=str(pid),
                name=raw.get("full_name") or f"{first} {last}".strip(),
                first_name=first or None,
                last_name=last or None,
                position=raw.get("position"),
                team=raw.get("team"),
                age=raw.get("age"),
                status=raw.get("status"),
            )
        )
    return players


def make_draft(
    draft_id: str = "D1",
    *,
    team_count: int = 12,
    rounds: int = 15,
    reversal_round: int = 0,
    status: str = "drafting",
    league_id: str | None = None,
    slot_to_roster: dict[int, int | None] | None = None,
    draft_order: dict[str, int] | None = None,
) -> DraftInfo:
    return DraftInfo(
        platform="fake",
        draft_id=draft_id,
        league_id=league_id,
        draft_type="snake",
        status=status,
        rounds=rounds,
        team_count=team_count,
        reversal_round=reversal_round,
        draft_order=draft_order,
        slot_to_roster=slot_to_roster or {},
    )


PLAYER_IDS = ["1001", "1002", "1003", "1004", "1005", "1006", "CAR"]


def make_pick(pick_no: int, player_id: str | None = None, team_count: int = 12) -> PickInfo:
    round_no = (pick_no - 1) // team_count + 1
    idx = (pick_no - 1) % team_count
    slot = idx + 1 if round_no % 2 == 1 else team_count - idx
    return PickInfo(
        pick_no=pick_no,
        round=round_no,
        draft_slot=slot,
        platform_player_id=player_id or PLAYER_IDS[(pick_no - 1) % len(PLAYER_IDS)],
        roster_id=slot,
    )


def make_picks(count: int, team_count: int = 12) -> list[PickInfo]:
    return [make_pick(no, team_count=team_count) for no in range(1, count + 1)]


class FakeAdapter(PlatformAdapter):
    """Scripted adapter: get_picks pops items off `picks_script` (an Exception item
    raises; the final item repeats forever)."""

    platform = "fake"
    poll_interval = 2.0
    traded_picks_interval = 60.0

    def __init__(
        self,
        *,
        draft: DraftInfo | None = None,
        picks_script: list | None = None,
        players: list[PlayerInfo] | None = None,
        traded: list[TradedPickInfo] | None = None,
        user: PlatformUser | None = None,
        leagues: list[LeagueInfo] | None = None,
    ) -> None:
        self.draft = draft or make_draft()
        self.picks_script = list(picks_script or [[]])
        self.players = players if players is not None else sample_players()
        self.traded = traded or []
        self.user = user
        self.leagues = leagues or []
        self.picks_calls = 0

    async def resolve_user(self, identifier: str) -> PlatformUser:
        if self.user is None or identifier not in (self.user.user_id, self.user.username):
            raise PlatformNotFound(f"user {identifier!r} not found")
        return self.user

    async def list_leagues(self, user_id: str, season: str) -> list[LeagueInfo]:
        return self.leagues

    async def get_league(self, league_id: str) -> LeagueInfo:
        for league in self.leagues:
            if league.league_id == league_id:
                return league
        raise PlatformNotFound(f"league {league_id!r} not found")

    async def list_drafts(self, league_id: str) -> list[DraftInfo]:
        return [self.draft]

    async def get_draft(self, draft_id: str) -> DraftInfo:
        return self.draft.model_copy(update={"draft_id": draft_id})

    async def get_picks(self, draft_id: str) -> list[PickInfo]:
        self.picks_calls += 1
        item = self.picks_script[0]
        if len(self.picks_script) > 1:
            self.picks_script.pop(0)
        if isinstance(item, Exception):
            raise item
        return list(item)

    async def get_traded_picks(self, draft_id: str) -> list[TradedPickInfo]:
        return self.traded

    async def get_players(self) -> list[PlayerInfo]:
        return self.players

    async def aclose(self) -> None:
        pass
