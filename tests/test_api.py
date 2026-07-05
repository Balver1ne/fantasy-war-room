import httpx
import pytest
from conftest import FakeAdapter, make_draft, make_picks
from warroom.app import create_app
from warroom.platforms.models import LeagueInfo, PlatformUser
from warroom.sync.draft_session import SessionManager
from warroom.sync.player_sync import PlayerSyncService

TEST_LEAGUE = LeagueInfo(
    platform="fake",
    league_id="222222222222222222",
    name="Test League",
    season="2026",
    team_count=12,
    scoring_preset="half_ppr",
    league_type="redraft",
)

TEST_USER = PlatformUser(
    platform="fake",
    user_id="111111111111111111",
    username="warroomtester",
    display_name="WarRoomTester",
)


@pytest.fixture
async def api(settings, session_factory, broker):
    """App wired with fakes directly on app.state (the lifespan never runs under
    ASGITransport, which is exactly what we want here)."""
    adapter = FakeAdapter(
        user=TEST_USER,
        leagues=[TEST_LEAGUE],
        draft=make_draft(draft_id="888888888888888888"),
        picks_script=[make_picks(3)],
    )
    app = create_app(settings)
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.adapter = adapter
    app.state.broker = broker
    app.state.player_sync = PlayerSyncService(adapter, session_factory)
    app.state.sessions = SessionManager(adapter, broker, session_factory, settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, app
    await app.state.sessions.stop_all()


async def test_health(api):
    client, _ = api
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["active_sessions"] == 0


async def test_resolve_user(api):
    client, _ = api
    resp = await client.get("/api/setup/users/warroomtester")
    assert resp.status_code == 200
    assert resp.json()["user_id"] == "111111111111111111"


async def test_resolve_unknown_user_404(api):
    client, _ = api
    resp = await client.get("/api/setup/users/ghost")
    assert resp.status_code == 404


async def test_league_discovery_and_connect(api):
    client, _ = api
    resp = await client.get("/api/setup/users/111111111111111111/leagues")
    assert resp.status_code == 200
    assert resp.json()[0]["league_id"] == "222222222222222222"

    resp = await client.post(
        "/api/leagues", json={"platform": "fake", "league_id": "222222222222222222"}
    )
    assert resp.status_code == 200

    resp = await client.get("/api/leagues")
    (league,) = resp.json()
    assert league["name"] == "Test League"
    assert league["scoring_preset"] == "half_ppr"


async def test_connect_unknown_league_404(api):
    client, _ = api
    resp = await client.post("/api/leagues", json={"platform": "fake", "league_id": "nope"})
    assert resp.status_code == 404


async def test_list_league_drafts(api):
    client, _ = api
    resp = await client.get("/api/leagues/222222222222222222/drafts")
    assert resp.status_code == 200
    assert resp.json()[0]["draft_id"] == "888888888888888888"


async def test_session_lifecycle(api):
    client, app = api
    resp = await client.post(
        "/api/drafts/888888888888888888/session", json={"my_slot": 4}
    )
    assert resp.status_code == 200
    snapshot = resp.json()
    assert snapshot["pick_count"] == 3
    assert snapshot["running"] is True
    assert snapshot["my_slot"] == 4

    resp = await client.get("/api/drafts/888888888888888888")
    assert resp.json()["pick_count"] == 3

    resp = await client.get("/api/drafts/888888888888888888/picks")
    picks = resp.json()
    assert len(picks) == 3
    assert picks[0]["player"]["name"] == "Christian McCaffrey"

    resp = await client.delete("/api/drafts/888888888888888888/session")
    assert resp.status_code == 200
    assert app.state.sessions.get("888888888888888888") is None


async def test_session_accepts_full_draft_url(api):
    client, _ = api
    resp = await client.post(
        "/api/drafts/https://sleeper.com/draft/nfl/888888888888888888/session",
        json={"my_slot": 2},
    )
    assert resp.status_code == 200
    assert resp.json()["draft_id"] == "888888888888888888"


async def test_get_state_without_session_404(api):
    client, _ = api
    resp = await client.get("/api/drafts/000000")
    assert resp.status_code == 404


async def test_players_sync_endpoint(api):
    client, _ = api
    resp = await client.post("/api/players/sync")
    assert resp.status_code == 200
    assert resp.json()["upserted"] == 7

    resp = await client.post("/api/players/sync")
    assert resp.json()["skipped"] is True

    resp = await client.post("/api/players/sync?force=true")
    assert resp.json()["upserted"] == 7
