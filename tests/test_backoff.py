from conftest import FakeAdapter, make_draft, make_picks
from warroom.sync.draft_session import DraftSession
from warroom.sync.player_sync import PlayerSyncService


async def test_backoff_stale_and_recovery(settings, session_factory, broker):
    """Four consecutive poll failures back off 2→4→8→10 (capped), emit exactly one
    `stale`, then the first success emits `recovered` and forces a full resync."""
    boom = RuntimeError("network blip")
    adapter = FakeAdapter(
        draft=make_draft(),
        picks_script=[
            make_picks(3),  # seed
            boom, boom, boom, boom,  # four failed polls
            make_picks(5),  # recovery poll
            make_picks(5),  # post-recovery reseed
        ],
    )
    await PlayerSyncService(adapter, session_factory).ensure_fresh()
    session = DraftSession("D1", adapter, broker, session_factory, settings, my_slot=4)

    delays: list[float] = []

    async def capture_sleep(delay: float) -> None:
        delays.append(delay)
        if broker.of_type("recovered"):
            session._stopping.set()

    session._sleep = capture_sleep

    await session._seed(initial=True)
    await session._run()

    # poll_interval=2, max_backoff=10: failures sleep 2→4→8→10, then normal cadence.
    assert delays[:4] == [2.0, 4.0, 8.0, 10.0]
    assert len(broker.of_type("stale")) == 1
    stale = broker.of_type("stale")[0]
    assert stale.data["consecutive_failures"] == 1
    assert stale.data["last_success"] is not None

    assert len(broker.of_type("recovered")) == 1
    # Two resyncs: session seed + forced reseed after recovery.
    assert len(broker.of_type("resync")) == 2
    assert session.last_pick_no == 5
    assert session.stale is False


async def test_stale_flag_visible_in_snapshot(settings, session_factory, broker):
    boom = RuntimeError("down")
    adapter = FakeAdapter(draft=make_draft(), picks_script=[make_picks(3), boom, boom])
    await PlayerSyncService(adapter, session_factory).ensure_fresh()
    session = DraftSession("D1", adapter, broker, session_factory, settings, my_slot=4)

    async def stop_after_two(delay: float) -> None:
        if len(broker.of_type("stale")) >= 1 and session._failures >= 2:
            session._stopping.set()

    session._sleep = stop_after_two

    await session._seed(initial=True)
    await session._run()

    assert session.stale is True
    assert session.snapshot()["stale"] is True
