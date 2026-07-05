import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from warroom.api.deps import get_db, get_player_sync, get_session_manager
from warroom.db import repo
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
