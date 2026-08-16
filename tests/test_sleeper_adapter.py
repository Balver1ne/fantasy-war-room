import httpx
import pytest
import respx
from conftest import load_fixture
from warroom.platforms.base import PlatformNotFound
from warroom.platforms.sleeper.adapter import SleeperAdapter

BASE = "http://sleeper.test/v1"


@pytest.fixture
async def adapter(settings):
    a = SleeperAdapter(settings)
    yield a
    await a.aclose()


@respx.mock
async def test_resolve_user(adapter):
    respx.get(f"{BASE}/user/warroomtester").mock(
        return_value=httpx.Response(200, json=load_fixture("user.json"))
    )
    user = await adapter.resolve_user("warroomtester")
    assert user.user_id == "111111111111111111"
    assert user.platform == "sleeper"


@respx.mock
async def test_resolve_user_null_body_raises_not_found(adapter):
    # Sleeper returns HTTP 200 with a literal JSON null body for unknown entities.
    respx.get(f"{BASE}/user/ghost").mock(
        return_value=httpx.Response(
            200, content=b"null", headers={"content-type": "application/json"}
        )
    )
    with pytest.raises(PlatformNotFound):
        await adapter.resolve_user("ghost")


@respx.mock
async def test_list_leagues_normalization(adapter):
    respx.get(f"{BASE}/user/111111111111111111/leagues/nfl/2026").mock(
        return_value=httpx.Response(200, json=load_fixture("leagues.json"))
    )
    leagues = await adapter.list_leagues("111111111111111111", "2026")
    half, dynasty = leagues

    assert half.scoring_preset == "half_ppr"
    assert half.league_type == "redraft"
    assert half.team_count == 12
    assert half.roster_slots["RB"] == 2
    assert half.roster_slots["BN"] == 1

    assert dynasty.scoring_preset == "ppr"
    assert dynasty.league_type == "dynasty"
    assert dynasty.roster_slots["SUPER_FLEX"] == 1


@respx.mock
async def test_get_draft_snake12(adapter):
    respx.get(f"{BASE}/draft/333333333333333333").mock(
        return_value=httpx.Response(200, json=load_fixture("draft_meta_snake12.json"))
    )
    draft = await adapter.get_draft("333333333333333333")
    assert draft.draft_type == "snake"
    assert draft.team_count == 12
    assert draft.rounds == 15
    assert draft.reversal_round == 0
    assert draft.league_id == "222222222222222222"
    assert draft.slot_to_roster == {slot: slot for slot in range(1, 13)}  # int keys
    assert draft.draft_order == {"111111111111111111": 4}


@respx.mock
async def test_get_draft_third_round_reversal(adapter):
    respx.get(f"{BASE}/draft/666666666666666666").mock(
        return_value=httpx.Response(200, json=load_fixture("draft_meta_3rr.json"))
    )
    draft = await adapter.get_draft("666666666666666666")
    assert draft.reversal_round == 3
    assert draft.slot_to_roster == {}
    assert draft.draft_order is None


@respx.mock
async def test_get_draft_mock_has_no_league(adapter):
    respx.get(f"{BASE}/draft/777777777777777777").mock(
        return_value=httpx.Response(200, json=load_fixture("draft_meta_mock.json"))
    )
    draft = await adapter.get_draft("777777777777777777")
    assert draft.league_id is None
    assert draft.status == "drafting"


@respx.mock
async def test_get_picks_sorted_and_coerced(adapter):
    picks_json = load_fixture("picks_progress/t2.json")
    respx.get(f"{BASE}/draft/333333333333333333/picks").mock(
        return_value=httpx.Response(200, json=list(reversed(picks_json)))
    )
    picks = await adapter.get_picks("333333333333333333")
    assert [p.pick_no for p in picks] == [1, 2, 3, 4, 5]
    assert picks[0].roster_id == 1  # "1" coerced to int
    assert picks[0].platform_player_id == "1001"
    assert picks[0].is_keeper is False  # null coerced


@respx.mock
async def test_get_traded_picks_mapping(adapter):
    respx.get(f"{BASE}/draft/333333333333333333/traded_picks").mock(
        return_value=httpx.Response(200, json=load_fixture("traded_picks.json"))
    )
    trades = await adapter.get_traded_picks("333333333333333333")
    assert (trades[0].round, trades[0].original_roster_id) == (2, 4)
    assert trades[0].current_owner_roster_id == 9


@respx.mock
async def test_get_players_names(adapter):
    respx.get(f"{BASE}/players/nfl").mock(
        return_value=httpx.Response(200, json=load_fixture("players_sample.json"))
    )
    players = {p.platform_player_id: p for p in await adapter.get_players()}
    assert players["1001"].name == "Christian McCaffrey"  # full_name used
    assert players["1004"].name == "Patrick Example"  # first + last fallback
    assert players["CAR"].name == "Carolina Panthers"  # D/ST
    assert players["CAR"].position == "DEF"
    assert players["1001"].age == 30


@respx.mock
async def test_scoring_preset_boundaries(adapter, settings):
    for rec, expected in [(0, "standard"), (0.5, "half_ppr"), (1.0, "ppr")]:
        league = dict(load_fixture("league.json"))
        league["scoring_settings"] = {"rec": rec}
        respx.get(f"{BASE}/league/L{rec}").mock(
            return_value=httpx.Response(200, json=league)
        )
        info = await adapter.get_league(f"L{rec}")
        assert info.scoring_preset == expected
