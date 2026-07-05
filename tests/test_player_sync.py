from datetime import UTC, datetime, timedelta

from conftest import FakeAdapter
from sqlalchemy import select
from warroom.db import repo
from warroom.db.models import Player
from warroom.sync.player_sync import SYNCED_AT_KEY, PlayerSyncService

SAMPLE_COUNT = 7


async def test_sync_then_cache_hit_then_force(settings, session_factory):
    adapter = FakeAdapter()
    svc = PlayerSyncService(adapter, session_factory)

    assert await svc.ensure_fresh() == SAMPLE_COUNT
    assert svc.is_fresh()
    assert await svc.ensure_fresh() == 0  # cache hit, no fetch
    assert await svc.ensure_fresh(force=True) == SAMPLE_COUNT


async def test_stale_cache_refetches(settings, session_factory):
    adapter = FakeAdapter()
    svc = PlayerSyncService(adapter, session_factory, max_age_hours=24)
    await svc.ensure_fresh()

    stale = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    with session_factory() as db:
        repo.set_meta(db, SYNCED_AT_KEY, stale)
        db.commit()

    assert not svc.is_fresh()
    assert await svc.ensure_fresh() == SAMPLE_COUNT


async def test_upsert_is_idempotent(settings, session_factory):
    adapter = FakeAdapter()
    svc = PlayerSyncService(adapter, session_factory)
    await svc.ensure_fresh()
    await svc.ensure_fresh(force=True)

    with session_factory() as db:
        rows = db.scalars(select(Player)).all()
    assert len(rows) == SAMPLE_COUNT  # updated in place, not duplicated


async def test_name_normalized_is_stored(settings, session_factory):
    adapter = FakeAdapter()
    await PlayerSyncService(adapter, session_factory).ensure_fresh()
    with session_factory() as db:
        harrison = db.get(Player, "1003")
        defense = db.get(Player, "CAR")
    assert harrison.name == "Marvin Harrison Jr."
    assert harrison.name_normalized == "marvin harrison"  # suffix + punctuation stripped
    assert defense.name_normalized == "carolina panthers"
