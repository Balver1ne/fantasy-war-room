import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from warroom.api.deps import get_db, get_player_sync, get_session_manager
from warroom.db import repo
from warroom.db.models import Draft
from warroom.engine import assemble
from warroom.engine.models import EngineConfig, Preferences
from warroom.engine.recommend import recommend
from warroom.platforms.base import PlatformNotFound
from warroom.sync.draft_session import SessionManager
from warroom.sync.player_sync import PlayerSyncService

router = APIRouter(prefix="/api", tags=["draft"])

Sessions = Annotated[SessionManager, Depends(get_session_manager)]
Db = Annotated[Session, Depends(get_db)]

# Accept a full Sleeper draft URL (https://sleeper.com/draft/nfl/<id>) or a bare id.
_DRAFT_ID = re.compile(r"(\d{6,})")


def _clean_draft_id(raw: str) -> str:
    if "/" not in raw:
        return raw  # bare id — pass through, whatever the platform's id shape is
    match = _DRAFT_ID.search(raw)
    if not match:
        raise HTTPException(status_code=400, detail=f"Cannot parse draft id from {raw!r}")
    return match.group(1)


class StartSessionRequest(BaseModel):
    my_slot: int | None = None
    my_roster_id: int | None = None
    my_user_id: str | None = None


@router.post("/drafts/{draft_id:path}/session")
async def start_session(
    draft_id: str,
    body: StartSessionRequest,
    sessions: Sessions,
    player_sync: Annotated[PlayerSyncService, Depends(get_player_sync)],
) -> dict[str, Any]:
    draft_id = _clean_draft_id(draft_id)
    # Pick logs must have names — make sure the universe is loaded before polling.
    await player_sync.ensure_fresh()
    try:
        session = await sessions.start_session(
            draft_id,
            my_slot=body.my_slot,
            my_roster_id=body.my_roster_id,
            my_user_id=body.my_user_id,
        )
    except PlatformNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return session.snapshot()


@router.delete("/drafts/{draft_id}/session")
async def stop_session(draft_id: str, sessions: Sessions) -> dict[str, Any]:
    stopped = await sessions.stop_session(draft_id)
    if not stopped:
        raise HTTPException(status_code=404, detail=f"No session for draft {draft_id}")
    return {"stopped": draft_id}


@router.get("/drafts/{draft_id}")
def get_draft_state(draft_id: str, sessions: Sessions) -> dict[str, Any]:
    session = sessions.get(draft_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"No session for draft {draft_id}")
    return session.snapshot()


@router.get("/drafts/{draft_id}/picks")
def get_draft_picks(draft_id: str, db: Db) -> list[dict[str, Any]]:
    picks = repo.get_picks(db, draft_id)
    players = repo.get_players_by_ids(db, [p.sleeper_id for p in picks])
    result = []
    for pick in picks:
        player = players.get(pick.sleeper_id)
        result.append(
            {
                "pick_no": pick.pick_no,
                "round": pick.round,
                "draft_slot": pick.draft_slot,
                "roster_id": pick.roster_id,
                "picked_by": pick.picked_by,
                "player": {
                    "id": pick.sleeper_id,
                    "name": player.name if player else None,
                    "position": player.position if player else None,
                    "team": player.team if player else None,
                },
            }
        )
    return result


def _source_labels(source_names: list[str]) -> dict[str, str]:
    """Short, unique display codes per ranking source (e.g. football_absurdity → FA)."""
    labels: dict[str, str] = {}
    used: set[str] = set()
    for name in source_names:
        parts = [p for p in re.split(r"[_\s]+", name) if p]
        ab = "".join(p[0] for p in parts).upper() if len(parts) >= 2 else name[:3].upper()
        base, i = ab, 2
        while ab in used:
            ab = f"{base}{i}"
            i += 1
        used.add(ab)
        labels[name] = ab
    return labels


def _breakdown(sid: str, position: str, data, labels: dict[str, str]):
    """Per-source view of a player: how each source ranks him within his position,
    plus any projection (Football Absurdity's pts/wk)."""
    out: list[dict[str, Any]] = []
    pts_wk: float | None = None
    for source, rows in data.sources.items():
        row = rows.get(sid)
        if row is None:
            continue
        entry: dict[str, Any] = {"source": source, "label": labels.get(source, source[:3].upper())}
        if row.position_rank is not None:
            entry["pos"] = f"{position}{row.position_rank}"
        elif row.rank is not None:
            entry["pos"] = f"#{row.rank}"
        if row.rank is not None:
            entry["overall"] = row.rank
        if row.projection is not None:
            entry["proj"] = round(row.projection, 1)
            if pts_wk is None:
                pts_wk = round(row.projection, 1)
        out.append(entry)
    return out, pts_wk


@router.get("/drafts/{draft_id}/recommendations")
def get_recommendations(
    draft_id: str,
    db: Db,
    sessions: Sessions,
    my_slot: int | None = None,
    scoring: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Best available picks for the drafting team, from the committed ranking sets +
    this draft's live pick state (Phase 3 engine over Phase 1/2 data)."""
    draft = db.get(Draft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail=f"No draft {draft_id} (start a session first)")

    session = sessions.get(draft_id)
    if my_slot is None and session is not None:
        my_slot = session.my_slot
    my_roster_id = session.my_roster_id if session is not None else None

    data = assemble.build_ranking_data(db, scoring or (draft.settings or {}).get("scoring_type"))
    if not data.players:
        raise HTTPException(
            status_code=400,
            detail="No active ranking sets — import rankings on /import first.",
        )
    league = assemble.build_league_from_draft(draft)
    state = assemble.build_draft_state(db, draft, my_slot=my_slot, my_roster_id=my_roster_id)
    config = EngineConfig(top_n=max(1, min(limit, 300)))
    result = recommend(state, data, Preferences(), league, config)

    picks_until = None
    if state.my_next_pick_no:
        picks_until = max(0, state.my_next_pick_no - state.current_pick_no)

    slots = {
        **league.starters,
        "FLEX": league.flex,
        "SUPER_FLEX": league.superflex,
        "BN": int((draft.settings or {}).get("slots_bn", 0) or 0),
    }

    labels = _source_labels(list(data.sources.keys()))
    recs = []
    for r in result.recommendations:
        breakdown, pts_wk = _breakdown(r.sleeper_id, r.position, data, labels)
        recs.append({
            "sleeper_id": r.sleeper_id, "name": r.name, "position": r.position,
            "team": r.team, "composite": r.composite_score, "vor": r.base_vor,
            "tier": r.tier, "survival": r.survival_prob, "flags": r.flags,
            "reasons": r.reasons, "pts_wk": pts_wk, "sources": breakdown,
        })

    return {
        "draft_id": draft_id,
        "my_slot": my_slot,
        "my_next_pick": state.my_next_pick_label,
        "my_next_pick_no": state.my_next_pick_no,
        "picks_until": picks_until,
        "pick_timer": draft.pick_timer,
        "needs": result.needs,
        "slots": {k: v for k, v in slots.items() if v},
        "source_labels": labels,
        "compute_ms": round(result.compute_ms, 1),
        "recommendations": recs,
    }


@router.post("/players/sync")
async def sync_players(
    player_sync: Annotated[PlayerSyncService, Depends(get_player_sync)],
    force: bool = False,
) -> dict[str, Any]:
    upserted = await player_sync.ensure_fresh(force=force)
    synced_at = player_sync.synced_at()
    return {
        "upserted": upserted,
        "synced_at": synced_at.isoformat() if synced_at else None,
        "skipped": upserted == 0,
    }
