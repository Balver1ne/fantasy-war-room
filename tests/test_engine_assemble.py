from types import SimpleNamespace

import httpx
import pytest
from warroom.app import create_app
from warroom.db.models import (
    Draft,
    DraftPick,
    FlagType,
    Player,
    PlayerFlag,
    Ranking,
    RankingSet,
)
from warroom.engine import assemble
from warroom.engine.models import Preferences
from warroom.engine.recommend import recommend
from warroom.names import normalize_name

BOARD = [
    ("1", "Bijan Robinson", "RB", 1),
    ("2", "Justin Jefferson", "WR", 2),
    ("3", "CeeDee Lamb", "WR", 3),
    ("4", "Christian McCaffrey", "RB", 4),
    ("5", "Jahmyr Gibbs", "RB", 5),
    ("6", "Puka Nacua", "WR", 6),
    ("7", "Josh Allen", "QB", 7),
    ("8", "Sam LaPorta", "TE", 8),
]
DRAFT_SETTINGS = {
    "slots_qb": 1, "slots_rb": 2, "slots_wr": 2, "slots_te": 1,
    "slots_k": 1, "slots_def": 1, "slots_flex": 1, "scoring_type": "half_ppr",
}


def seed(session_factory):
    with session_factory() as s:
        for sid, name, pos, _ in BOARD:
            s.add(Player(sleeper_id=sid, name=name, name_normalized=normalize_name(name),
                         position=pos, team="X"))
        rset = RankingSet(source="FantasyPros", kind="rankings", scoring_format="half_ppr",
                          active=True, row_count=len(BOARD))
        s.add(rset)
        s.flush()
        for sid, _, _, rank in BOARD:
            s.add(Ranking(ranking_set_id=rset.id, sleeper_id=sid, rank=rank, adp=float(rank)))
        s.add(FlagType(flag_name="sleeper", value_kind="bool", tiebreak_priority=10))
        s.add(PlayerFlag(sleeper_id="5", flag_name="sleeper", value_bool=True,
                         ranking_set_id=rset.id))
        s.add(Draft(draft_id="D1", platform="sleeper", type="snake", status="drafting",
                    rounds=15, team_count=12, settings=DRAFT_SETTINGS,
                    slot_to_roster={}))
        # picks 1 and 2 already made (Bijan, Jefferson)
        s.add(DraftPick(draft_id="D1", pick_no=1, sleeper_id="1", round=1, draft_slot=1))
        s.add(DraftPick(draft_id="D1", pick_no=2, sleeper_id="2", round=1, draft_slot=2))
        s.commit()


def test_build_ranking_data_from_db(session_factory):
    seed(session_factory)
    with session_factory() as s:
        data = assemble.build_ranking_data(s, "half_ppr")
    assert "FantasyPros" in data.sources
    assert data.players["1"].name == "Bijan Robinson"
    assert data.adp["4"] == 4.0
    assert data.flags["5"]["sleeper"] is True
    assert data.flag_priority["sleeper"] == 10


def test_adp_two_tier_imported_then_search_rank(session_factory):
    with session_factory() as s:
        s.add(Player(sleeper_id="a", name="A", name_normalized="a", position="RB",
                     team="X", metadata_json={"search_rank": 18}))
        s.add(Player(sleeper_id="b", name="B", name_normalized="b", position="WR",
                     team="X", metadata_json={"search_rank": 9999999}))  # sentinel
        s.add(Player(sleeper_id="c", name="C", name_normalized="c", position="RB",
                     team="X", metadata_json={"search_rank": 50}))
        rset = RankingSet(source="FP", kind="rankings", scoring_format="half_ppr",
                          active=True, row_count=3)
        s.add(rset)
        s.flush()
        s.add(Ranking(ranking_set_id=rset.id, sleeper_id="a", rank=1))            # no ADP
        s.add(Ranking(ranking_set_id=rset.id, sleeper_id="b", rank=2))            # sentinel
        s.add(Ranking(ranking_set_id=rset.id, sleeper_id="c", rank=3, adp=99.0))  # imported
        s.commit()
    with session_factory() as s:
        data = assemble.build_ranking_data(s, "half_ppr")
    assert data.adp["a"] == 18.0     # proxy from search_rank
    assert "b" not in data.adp       # 9999999 sentinel filtered out
    assert data.adp["c"] == 99.0     # imported ADP overrides the search_rank proxy


def test_build_league_from_draft_slots(session_factory):
    seed(session_factory)
    with session_factory() as s:
        draft = s.get(Draft, "D1")
        league = assemble.build_league_from_draft(draft)
    assert league.starters["RB"] == 2 and league.starters["QB"] == 1
    assert league.flex == 1 and league.team_count == 12


def test_end_to_end_recommend_from_db(session_factory):
    seed(session_factory)
    with session_factory() as s:
        draft = s.get(Draft, "D1")
        data = assemble.build_ranking_data(s, "half_ppr")
        league = assemble.build_league_from_draft(draft)
        state = assemble.build_draft_state(s, draft, my_slot=3)
        res = recommend(state, data, Preferences(), league)
    ids = {r.sleeper_id for r in res.recommendations}
    assert ids.isdisjoint({"1", "2"})            # drafted excluded
    assert res.recommendations                    # something recommended


@pytest.fixture
async def api(settings, session_factory):
    seed(session_factory)
    app = create_app(settings)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.sessions = SimpleNamespace(get=lambda draft_id: None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def test_recommendations_endpoint(api):
    r = await api.get("/api/drafts/D1/recommendations?my_slot=3")
    assert r.status_code == 200
    body = r.json()
    assert body["my_slot"] == 3
    assert body["recommendations"]
    top = body["recommendations"][0]
    assert top["sleeper_id"] not in ("1", "2")
    assert "reasons" in top and isinstance(top["reasons"], list)
    assert body["needs"]["RB"] >= 1


async def test_recommendations_board_fields(api):
    r = await api.get("/api/drafts/D1/recommendations?my_slot=3&limit=50")
    b = r.json()
    assert b["slots"]["RB"] == 2 and b["slots"]["FLEX"] == 1
    assert "picks_until" in b and "my_next_pick_no" in b and "pick_timer" in b
    assert b["board"], "value-ordered board returned"
    be = b["board"][0]
    assert "value" in be and "vorp" in be and "vona" in be
    # board is value-ordered
    vals = [e["value"] for e in b["board"]]
    assert vals == sorted(vals, reverse=True)


async def test_recommendations_source_breakdown(api):
    r = await api.get("/api/drafts/D1/recommendations?my_slot=3&limit=50")
    b = r.json()
    assert "source_labels" in b and "FantasyPros" in b["source_labels"]
    rec = b["recommendations"][0]
    assert "sources" in rec and rec["sources"]
    src = rec["sources"][0]
    assert "label" in src and "overall" in src   # seeded board has overall ranks
    assert "pts_wk" in rec                         # present (None here — no projection seeded)


async def test_board_page_served(api):
    r = await api.get("/board")
    assert r.status_code == 200 and "WAR ROOM" in r.text


async def test_recommendations_requires_rankings(settings, session_factory):
    # draft exists but no ranking sets committed
    with session_factory() as s:
        s.add(Draft(draft_id="D2", platform="sleeper", type="snake", status="drafting",
                    rounds=15, team_count=12, settings=DRAFT_SETTINGS, slot_to_roster={}))
        s.commit()
    app = create_app(settings)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.sessions = SimpleNamespace(get=lambda draft_id: None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/drafts/D2/recommendations?my_slot=1")
    assert r.status_code == 400
