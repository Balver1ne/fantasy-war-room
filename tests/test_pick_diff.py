from conftest import FakeAdapter, make_draft, make_picks, sample_players
from warroom.db import repo
from warroom.sync.draft_session import DraftSession
from warroom.sync.player_sync import PlayerSyncService


async def seed_players(adapter, session_factory):
    await PlayerSyncService(adapter, session_factory).ensure_fresh()


def make_session(adapter, broker, session_factory, settings, **identity) -> DraftSession:
    return DraftSession(
        "D1", adapter, broker, session_factory, settings, **identity
    )


async def test_seed_then_new_picks(settings, session_factory, broker):
    adapter = FakeAdapter(
        draft=make_draft(), picks_script=[make_picks(3), make_picks(5)]
    )
    await seed_players(adapter, session_factory)
    session = make_session(adapter, broker, session_factory, settings, my_slot=4)
    await session._seed(initial=True)

    assert session.last_pick_no == 3
    assert len(broker.of_type("resync")) == 1
    assert broker.of_type("pick") == []

    new = await session._poll_once()
    assert [p.pick_no for p in new] == [4, 5]
    pick_events = broker.of_type("pick")
    assert [e.data["pick_no"] for e in pick_events] == [4, 5]
    assert len(broker.of_type("on_clock")) == 1

    with session_factory() as db:
        assert [p.pick_no for p in repo.get_picks(db, "D1")] == [1, 2, 3, 4, 5]


async def test_no_new_picks_no_events(settings, session_factory, broker):
    adapter = FakeAdapter(draft=make_draft(), picks_script=[make_picks(3)])
    await seed_players(adapter, session_factory)
    session = make_session(adapter, broker, session_factory, settings, my_slot=4)
    await session._seed(initial=True)
    broker.events.clear()

    new = await session._poll_once()
    assert new == []
    assert broker.events == []


async def test_pick_payload_resolves_player_names(settings, session_factory, broker):
    adapter = FakeAdapter(draft=make_draft(), picks_script=[[], make_picks(1)])
    await seed_players(adapter, session_factory)
    session = make_session(adapter, broker, session_factory, settings, my_slot=4)
    await session._seed(initial=True)

    await session._poll_once()
    (pick_event,) = broker.of_type("pick")
    assert pick_event.data["player"]["name"] == "Christian McCaffrey"
    assert pick_event.data["player"]["position"] == "RB"
    assert pick_event.data["label"] == "1.01"


async def test_on_clock_payload_mock_mode(settings, session_factory, broker):
    adapter = FakeAdapter(draft=make_draft(), picks_script=[make_picks(3)])
    await seed_players(adapter, session_factory)
    session = make_session(adapter, broker, session_factory, settings, my_slot=4)
    await session._seed(initial=True)

    snapshot = session.snapshot()
    on_clock = snapshot["on_clock"]
    assert on_clock["next_pick_no"] == 4
    assert on_clock["picks_until_me"] == 0
    assert on_clock["alert"] is True


async def test_identity_resolution_from_user_id(settings, session_factory, broker):
    draft = make_draft(
        draft_order={"111111111111111111": 4},
        slot_to_roster={slot: slot for slot in range(1, 13)},
    )
    adapter = FakeAdapter(draft=draft, picks_script=[[]])
    await seed_players(adapter, session_factory)
    session = make_session(
        adapter, broker, session_factory, settings, my_user_id="111111111111111111"
    )
    await session._seed(initial=True)
    assert session.my_slot == 4
    assert session.my_roster_id == 4


def test_players_seeded_for_reference():
    # keep the fixture honest: the pick generator only uses ids present in the sample
    ids = {p.platform_player_id for p in sample_players()}
    assert {"1001", "1002", "1003", "1004", "1005", "1006", "CAR"} <= ids
