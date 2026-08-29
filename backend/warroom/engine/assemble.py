"""Build engine inputs from the database + a draft's stored state.

Bridges the ingested ranking sets (Phase 2) and the live draft mirror (Phase 1) to the
pure engine (Phase 3): DB rows in, RankingData / LeagueSettings / DraftState out.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from warroom.db.models import (
    Draft,
    DraftPick,
    FlagType,
    Player,
    PlayerFlag,
    Ranking,
    RankingSet,
)
from warroom.engine.models import (
    DraftState,
    LeagueSettings,
    PlayerMeta,
    RankingData,
    RankRow,
)
from warroom.sync import snake

# Sleeper marks irrelevant players with this search_rank; treat as "no ADP".
_SEARCH_RANK_SENTINEL = 9_000_000

# Sleeper draft settings slot keys → engine starter positions.
_SLOT_KEYS = {
    "QB": "slots_qb", "RB": "slots_rb", "WR": "slots_wr",
    "TE": "slots_te", "K": "slots_k", "DEF": "slots_def",
}


def build_ranking_data(session: Session, scoring_format: str | None = None) -> RankingData:
    sets = list(
        session.scalars(
            select(RankingSet).where(RankingSet.active.is_(True)).order_by(RankingSet.imported_at)
        )
    )
    if scoring_format:
        sets = [s for s in sets if s.kind == "adp" or s.scoring_format == scoring_format]

    sources: dict[str, dict[str, RankRow]] = {}
    weights: dict[str, float] = {}
    adp: dict[str, float] = {}
    referenced: set[str] = set()

    for rset in sets:
        rows = list(session.scalars(select(Ranking).where(Ranking.ranking_set_id == rset.id)))
        if rset.kind == "rankings":
            table = sources.setdefault(rset.source, {})
            weights[rset.source] = 1.0
            for r in rows:
                table[r.sleeper_id] = RankRow(
                    rank=r.rank, position_rank=r.position_rank, projection=r.projection
                )
                referenced.add(r.sleeper_id)
        for r in rows:
            if r.adp is not None:
                adp[r.sleeper_id] = r.adp
                referenced.add(r.sleeper_id)

    flags: dict[str, dict[str, float | bool]] = {}
    for pf in session.scalars(select(PlayerFlag)):
        value: float | bool | None = pf.value_bool if pf.value_bool is not None else pf.value_num
        if value is None:
            continue
        flags.setdefault(pf.sleeper_id, {})[pf.flag_name] = value
        referenced.add(pf.sleeper_id)

    flag_priority: dict[str, int] = {}
    flag_kinds: dict[str, str] = {}
    for ft in session.scalars(select(FlagType)):
        flag_priority[ft.flag_name] = ft.tiebreak_priority
        flag_kinds[ft.flag_name] = ft.value_kind

    players: dict[str, PlayerMeta] = {}
    if referenced:
        for p in session.scalars(select(Player).where(Player.sleeper_id.in_(referenced))):
            players[p.sleeper_id] = PlayerMeta(p.sleeper_id, p.name, p.position or "?", p.team)
            # Two-tier ADP: imported ADP wins; otherwise fall back to Sleeper's live
            # `search_rank` (a popularity/ADP-like ordering synced daily), skipping the
            # 9999999 "irrelevant" sentinel. Keeps survival probability working with no
            # ADP import.
            if p.sleeper_id not in adp:
                sr = (p.metadata_json or {}).get("search_rank")
                if isinstance(sr, (int, float)) and 0 < sr < _SEARCH_RANK_SENTINEL:
                    adp[p.sleeper_id] = float(sr)

    return RankingData(
        players=players, sources=sources, weights=weights,
        adp=adp, flags=flags, flag_priority=flag_priority, flag_kinds=flag_kinds,
    )


def build_league_from_draft(draft: Draft) -> LeagueSettings:
    settings = draft.settings or {}
    starters = {pos: int(settings.get(key, 0) or 0) for pos, key in _SLOT_KEYS.items()}
    return LeagueSettings(
        team_count=draft.team_count or 12,
        starters=starters,
        flex=int(settings.get("slots_flex", 0) or 0),
        superflex=int(settings.get("slots_super_flex", 0) or 0),
    )


def _order_config(draft: Draft) -> snake.DraftOrderConfig:
    slot_map = draft.slot_to_roster or {}
    return snake.DraftOrderConfig(
        team_count=draft.team_count or 0,
        rounds=draft.rounds or 0,
        draft_type="linear" if draft.type == "linear" else "snake",
        reversal_round=draft.reversal_round or 0,
        slot_to_roster={int(k): v for k, v in slot_map.items()},
        traded={},
    )


def build_draft_state(
    session: Session,
    draft: Draft,
    *,
    my_slot: int | None = None,
    my_roster_id: int | None = None,
    recent_window: int = 5,
) -> DraftState:
    picks = list(
        session.scalars(
            select(DraftPick).where(DraftPick.draft_id == draft.draft_id)
            .order_by(DraftPick.pick_no)
        )
    )
    drafted = {p.sleeper_id for p in picks}
    positions = {p.sleeper_id: (session.get(Player, p.sleeper_id).position
                                if session.get(Player, p.sleeper_id) else None)
                 for p in picks}

    my_roster = [
        p.sleeper_id for p in picks
        if (my_roster_id is not None and p.roster_id == my_roster_id)
        or (my_roster_id is None and my_slot is not None and p.draft_slot == my_slot)
    ]
    recent_positions = [positions[p.sleeper_id] for p in picks[-recent_window:]
                        if positions.get(p.sleeper_id)]
    last_pick = max((p.pick_no for p in picks), default=0)

    cfg = _order_config(draft)
    my_next_pick_no = None
    my_next_pick_label = None
    if cfg.team_count and (my_slot is not None or my_roster_id is not None):
        my_next_pick_no = snake.next_pick_no_for(
            last_pick, cfg,
            roster_id=my_roster_id,
            slot=my_slot if my_roster_id is None else None,
        )
        if my_next_pick_no:
            my_next_pick_label = snake.format_pick(my_next_pick_no, cfg)

    return DraftState(
        drafted=drafted,
        my_roster=my_roster,
        recent_positions=recent_positions,
        current_pick_no=last_pick + 1,
        my_next_pick_no=my_next_pick_no,
        my_next_pick_label=my_next_pick_label,
    )
