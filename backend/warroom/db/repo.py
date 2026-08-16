"""Persistence helpers: normalized platform DTOs in, ORM rows out."""

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from warroom.db.models import (
    Draft,
    DraftPick,
    League,
    Meta,
    Player,
    PlayerAlias,
    utcnow,
)
from warroom.matching.engine import PlayerRef
from warroom.names import normalize_name
from warroom.platforms.models import DraftInfo, LeagueInfo, PickInfo, PlayerInfo


def get_meta(session: Session, key: str) -> str | None:
    row = session.get(Meta, key)
    return row.value if row else None


def set_meta(session: Session, key: str, value: str) -> None:
    session.merge(Meta(key=key, value=value, updated_at=utcnow()))


def get_meta_datetime(session: Session, key: str) -> datetime | None:
    raw = get_meta(session, key)
    return datetime.fromisoformat(raw) if raw else None


def upsert_league(session: Session, info: LeagueInfo) -> League:
    league = League(
        league_id=info.league_id,
        platform=info.platform,
        name=info.name,
        season=info.season,
        team_count=info.team_count,
        league_type=info.league_type,
        scoring_preset=info.scoring_preset,
        settings={**info.raw_settings, "roster_slots": info.roster_slots},
        scoring=info.scoring,
        last_synced_at=utcnow(),
    )
    return session.merge(league)


def upsert_draft(session: Session, info: DraftInfo) -> Draft:
    draft = Draft(
        draft_id=info.draft_id,
        league_id=info.league_id,
        platform=info.platform,
        type=info.draft_type,
        status=info.status,
        rounds=info.rounds,
        team_count=info.team_count,
        reversal_round=info.reversal_round,
        pick_timer=info.pick_timer,
        settings=info.raw_settings,
        draft_order=info.draft_order,
        slot_to_roster={str(k): v for k, v in info.slot_to_roster.items()},
        last_synced_at=utcnow(),
    )
    return session.merge(draft)


def upsert_players(session: Session, players: list[PlayerInfo]) -> int:
    """Bulk upsert the full universe (~11k rows) in one statement."""
    if not players:
        return 0
    now = utcnow()
    rows = [
        {
            "sleeper_id": p.platform_player_id,
            "name": p.name,
            "name_normalized": normalize_name(p.name),
            "position": p.position,
            "team": p.team,
            "age": p.age,
            "status": p.status,
            "metadata_json": p.metadata,
            "updated_at": now,
        }
        for p in players
    ]
    stmt = sqlite_insert(Player)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Player.sleeper_id],
        set_={
            col: getattr(stmt.excluded, col)
            for col in ("name", "name_normalized", "position", "team", "age", "status",
                        "metadata_json", "updated_at")
        },
    )
    session.execute(stmt, rows)
    return len(rows)


def _pick_row(draft_id: str, pick: PickInfo) -> DraftPick:
    return DraftPick(
        draft_id=draft_id,
        pick_no=pick.pick_no,
        sleeper_id=pick.platform_player_id,
        round=pick.round,
        draft_slot=pick.draft_slot,
        roster_id=pick.roster_id,
        picked_by=pick.picked_by,
        is_keeper=pick.is_keeper,
        metadata_json=pick.metadata,
        observed_at=utcnow(),
    )


def replace_picks(session: Session, draft_id: str, picks: list[PickInfo]) -> None:
    """Wholesale replace — Sleeper's pick list is the source of truth (resync path)."""
    session.execute(delete(DraftPick).where(DraftPick.draft_id == draft_id))
    session.add_all(_pick_row(draft_id, p) for p in picks)


def append_picks(session: Session, draft_id: str, picks: list[PickInfo]) -> None:
    session.add_all(_pick_row(draft_id, p) for p in picks)


def get_picks(session: Session, draft_id: str) -> list[DraftPick]:
    stmt = (
        select(DraftPick)
        .where(DraftPick.draft_id == draft_id)
        .order_by(DraftPick.pick_no)
    )
    return list(session.scalars(stmt))


def get_players_by_ids(session: Session, sleeper_ids: list[str]) -> dict[str, Player]:
    if not sleeper_ids:
        return {}
    stmt = select(Player).where(Player.sleeper_id.in_(sleeper_ids))
    return {p.sleeper_id: p for p in session.scalars(stmt)}


def load_player_refs(session: Session) -> list[PlayerRef]:
    """Snapshot the player universe as match-index inputs."""
    return [
        PlayerRef(
            sleeper_id=p.sleeper_id,
            name=p.name,
            name_normalized=p.name_normalized,
            position=p.position,
            team=p.team,
        )
        for p in session.scalars(select(Player))
    ]


def load_aliases(session: Session) -> dict[str, str]:
    """alias_normalized -> sleeper_id (latest wins)."""
    aliases: dict[str, str] = {}
    for a in session.scalars(select(PlayerAlias).order_by(PlayerAlias.created_at)):
        aliases[a.alias_normalized] = a.sleeper_id
    return aliases


def add_alias(session: Session, alias_normalized: str, sleeper_id: str, source: str | None) -> None:
    session.add(
        PlayerAlias(alias_normalized=alias_normalized, sleeper_id=sleeper_id, source=source)
    )
