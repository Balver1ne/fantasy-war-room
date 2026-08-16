import asyncio
import json

import httpx
import pytest
from conftest import FakeAdapter, make_picks
from warroom.api.routes_stream import event_stream
from warroom.app import create_app
from warroom.events.broker import QUEUE_SIZE, Event, EventBroker
from warroom.sync.draft_session import SessionManager
from warroom.sync.player_sync import PlayerSyncService


def ev(seq: int, type_: str = "pick", draft_id: str = "D1", **data) -> Event:
    return Event(seq=seq, type=type_, draft_id=draft_id, data=data)


async def test_fanout_to_multiple_subscribers():
    broker = EventBroker()
    async with broker.subscribe("D1") as q1, broker.subscribe("D1") as q2:
        broker.publish(ev(1, pick_no=1))
        assert (await asyncio.wait_for(q1.get(), 1)).data["pick_no"] == 1
        assert (await asyncio.wait_for(q2.get(), 1)).data["pick_no"] == 1


async def test_events_isolated_per_draft():
    broker = EventBroker()
    async with broker.subscribe("D1") as q1, broker.subscribe("D2") as q2:
        broker.publish(ev(1, draft_id="D2"))
        assert q1.empty()
        assert (await asyncio.wait_for(q2.get(), 1)).seq == 1


async def test_slow_consumer_is_dropped():
    broker = EventBroker()
    async with broker.subscribe("D1"):
        assert broker.subscriber_count("D1") == 1
        for seq in range(QUEUE_SIZE + 1):
            broker.publish(ev(seq))
        assert broker.subscriber_count("D1") == 0


async def test_unsubscribe_cleans_up():
    broker = EventBroker()
    async with broker.subscribe("D1"):
        pass
    assert broker.subscriber_count("D1") == 0


@pytest.fixture
async def api(settings, session_factory, broker):
    adapter = FakeAdapter(picks_script=[make_picks(3)])
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


async def test_event_stream_greeting_then_live_events(api):
    """New subscribers get a resync snapshot greeting; published events then flow.

    Driven at the generator level: httpx's ASGITransport buffers whole responses,
    so an infinite SSE body can't be consumed over it.
    """
    _, app = api
    broker = app.state.broker
    gen = event_stream("D9", broker, app.state.sessions)

    greeting = await asyncio.wait_for(anext(gen), timeout=2)
    assert greeting["event"] == "resync"
    assert json.loads(greeting["data"])["status"] == "no_session"

    broker.publish(ev(42, draft_id="D9", pick_no=7))
    live = await asyncio.wait_for(anext(gen), timeout=2)
    assert live["event"] == "pick"
    assert live["id"] == "42"
    payload = json.loads(live["data"])
    assert payload["pick_no"] == 7
    assert "ts" in payload

    await gen.aclose()
    assert broker.subscriber_count("D9") == 0


async def test_event_stream_greeting_reflects_running_session(api):
    client, app = api
    resp = await client.post("/api/drafts/D7/session", json={"my_slot": 4})
    assert resp.status_code == 200

    gen = event_stream("D7", app.state.broker, app.state.sessions)
    greeting = await asyncio.wait_for(anext(gen), timeout=2)
    snapshot = json.loads(greeting["data"])
    assert snapshot["pick_count"] == 3
    assert snapshot["status"] == "drafting"
    await gen.aclose()
