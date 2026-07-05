from conftest import FakeAdapter, make_draft, make_pick, make_picks
from warroom.db import repo
from warroom.sync.draft_session import DraftSession
from warroom.sync.player_sync import PlayerSyncService


async def build(settings, session_factory, broker, picks_script) -> DraftSession:
    adapter = FakeAdapter(draft=make_draft(), picks_script=picks_script)
    await PlayerSyncService(adapter, session_factory).ensure_fresh()
    session = DraftSession("D1", adapter, broker, session_factory, settings, my_slot=4)
    await session._seed(initial=True)
    return session


async def test_catch_up_after_restart(settings, session_factory, broker):
    """Seed at 8 picks, then the fetched list has 14 → exactly 6 pick events."""
    session = await build(settings, session_factory, broker, [make_picks(8), make_picks(14)])
    await session._poll_once()

    assert [e.data["pick_no"] for e in broker.of_type("pick")] == [9, 10, 11, 12, 13, 14]
    assert len(broker.of_type("resync")) == 1  # only the seed
    assert session.last_pick_no == 14


async def test_anomaly_changed_pick_triggers_full_resync(settings, session_factory, broker):
    """Commissioner undo: overlapping pick_no with a different player → wholesale replace."""
    changed = make_picks(8)
    changed[4] = make_pick(5, player_id="1006")  # pick 5 now a different player
    session = await build(
        settings, session_factory, broker, [make_picks(8), changed, changed]
    )
    broker.events.clear()

    new = await session._poll_once()
    assert new == []
    assert len(broker.of_type("resync")) == 1
    assert broker.of_type("pick") == []  # replace, not incremental events
    with session_factory() as db:
        rows = {p.pick_no: p.sleeper_id for p in repo.get_picks(db, "D1")}
    assert rows[5] == "1006"


async def test_anomaly_shorter_list_triggers_full_resync(settings, session_factory, broker):
    session = await build(
        settings, session_factory, broker, [make_picks(8), make_picks(6), make_picks(6)]
    )
    broker.events.clear()

    await session._poll_once()
    assert len(broker.of_type("resync")) == 1
    assert session.last_pick_no == 6
    with session_factory() as db:
        assert len(repo.get_picks(db, "D1")) == 6


async def test_restart_resyncs_from_platform_truth(settings, session_factory, broker):
    """Simulate app restart mid-draft: a fresh session over the same DB converges to
    the platform pick list within one seed (DESIGN.md resume-safety)."""
    session = await build(settings, session_factory, broker, [make_picks(8)])
    assert session.last_pick_no == 8

    # "Restart": new session object, same database, draft has advanced to 14 picks.
    adapter = FakeAdapter(draft=make_draft(), picks_script=[make_picks(14)])
    restarted = DraftSession("D1", adapter, broker, session_factory, settings, my_slot=4)
    await restarted._seed(initial=True)

    assert restarted.last_pick_no == 14
    assert restarted.snapshot()["pick_count"] == 14
    with session_factory() as db:
        assert len(repo.get_picks(db, "D1")) == 14
