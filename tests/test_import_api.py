from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from warroom.app import create_app
from warroom.db.models import Player, PlayerFlag
from warroom.names import normalize_name

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "ingest"

UNIVERSE = [
    ("1001", "Christian McCaffrey", "RB", "SF"),
    ("1002", "Justin Jefferson", "WR", "MIN"),
    ("1005", "Bijan Robinson", "RB", "ATL"),
    ("1003", "Marvin Harrison Jr.", "WR", "ARI"),
    ("1010", "Amon-Ra St. Brown", "WR", "DET"),
]


@pytest.fixture
async def api(settings, session_factory):
    with session_factory() as s:
        for sid, name, pos, team in UNIVERSE:
            s.add(Player(sleeper_id=sid, name=name, name_normalized=normalize_name(name),
                         position=pos, team=team))
        s.commit()
    app = create_app(settings)
    app.state.settings = settings
    app.state.session_factory = session_factory
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, session_factory


async def _upload_fp(client):
    content = (FIXTURES / "fantasypros_sample.csv").read_bytes()
    return await client.post(
        "/api/imports/upload",
        files={"file": ("fantasypros_sample.csv", content, "text/csv")},
        data={"source": "FantasyPros", "scoring_format": "half_ppr", "league_type": "redraft"},
    )


async def test_upload_auto_maps_and_previews(api):
    client, _ = api
    r = await _upload_fp(client)
    assert r.status_code == 200
    job = r.json()
    assert job["file_kind"] == "csv"
    assert job["row_count"] == 6
    assert job["mappings"]["PLAYER NAME"] == "name"
    assert job["mappings"]["POS"] == "position"
    assert len(job["preview"]) == 6


async def test_full_flow_to_commit_with_flag(api):
    client, sf = api
    job = (await _upload_fp(client)).json()
    jid = job["id"]

    # map the confidence column to a numeric flag
    mapping = dict(job["mappings"])
    mapping["RB_CONFIDENCE"] = "flag:rb_confidence:numeric"
    await client.put(f"/api/imports/{jid}/mapping", json={"mappings": mapping})

    r = await client.post(f"/api/imports/{jid}/match")
    summary = r.json()["summary"]
    assert summary["matched"] == 5 and summary["unmatched"] == 1

    # the unknown rookie is unresolved; commit must be blocked
    blocked = await client.post(f"/api/imports/{jid}/commit", json={})
    assert blocked.status_code == 400

    # skip it, then commit succeeds
    unmatched = (await client.get(f"/api/imports/{jid}")).json()["unmatched"]
    await client.post(f"/api/imports/{jid}/skip", json={"row_index": unmatched[0]["row_index"]})
    done = await client.post(f"/api/imports/{jid}/commit", json={"label": "FP test"})
    assert done.status_code == 200
    body = done.json()
    assert body["row_count"] == 5 and body["scoring_format"] == "half_ppr"

    with sf() as s:
        flags = s.scalars(select(PlayerFlag)).all()
        assert len(flags) == 5
        assert any(f.sleeper_id == "1001" and f.value_num == 5.0 for f in flags)


async def test_manual_resolve_via_api_learns_alias(api):
    client, _ = api
    job = (await _upload_fp(client)).json()
    jid = job["id"]
    await client.post(f"/api/imports/{jid}/match")
    unmatched = (await client.get(f"/api/imports/{jid}")).json()["unmatched"]
    idx = unmatched[0]["row_index"]
    r = await client.post(
        f"/api/imports/{jid}/resolve", json={"row_index": idx, "sleeper_id": "1001"}
    )
    assert r.status_code == 200
    assert r.json()["unresolved"] == 0


async def test_player_search(api):
    client, _ = api
    r = await client.get("/api/players/search?q=mccaffrey")
    hits = r.json()
    assert hits and hits[0]["sleeper_id"] == "1001"
    r2 = await client.get("/api/players/search?q=robinson&position=RB")
    assert all(h["position"] == "RB" for h in r2.json())


async def test_paste_import(api):
    client, _ = api
    text = "name,position,team\nChristian McCaffrey,RB,SF\nBijan Robinson,RB,ATL\n"
    r = await client.post("/api/imports/paste", json={
        "text": text, "source": "paste", "scoring_format": "half_ppr"})
    assert r.status_code == 200
    assert r.json()["file_kind"] == "paste"
    assert r.json()["row_count"] == 2


async def test_ranking_sets_listing(api):
    client, _ = api
    job = (await _upload_fp(client)).json()
    jid = job["id"]
    await client.post(f"/api/imports/{jid}/match")
    unmatched = (await client.get(f"/api/imports/{jid}")).json()["unmatched"]
    await client.post(f"/api/imports/{jid}/skip", json={"row_index": unmatched[0]["row_index"]})
    await client.post(f"/api/imports/{jid}/commit", json={})
    sets = (await client.get("/api/rankings/sets")).json()
    assert len(sets) == 1 and sets[0]["active"] is True
