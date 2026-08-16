from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from warroom.api.deps import get_adapter, get_db, get_settings
from warroom.config import Settings
from warroom.db import repo
from warroom.db.models import League
from warroom.platforms.base import PlatformAdapter, PlatformNotFound
from warroom.platforms.models import DraftInfo, LeagueInfo, PlatformUser

router = APIRouter(prefix="/api", tags=["setup"])

Adapter = Annotated[PlatformAdapter, Depends(get_adapter)]
Db = Annotated[Session, Depends(get_db)]


@router.get("/setup/users/{identifier}")
async def resolve_user(identifier: str, adapter: Adapter) -> PlatformUser:
    try:
        return await adapter.resolve_user(identifier)
    except PlatformNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/setup/users/{user_id}/leagues")
async def list_user_leagues(
    user_id: str,
    adapter: Adapter,
    settings: Annotated[Settings, Depends(get_settings)],
    season: str | None = None,
) -> list[LeagueInfo]:
    return await adapter.list_leagues(user_id, season or settings.season)


class ConnectLeagueRequest(BaseModel):
    league_id: str
    platform: str = "sleeper"


@router.post("/leagues")
async def connect_league(body: ConnectLeagueRequest, adapter: Adapter, db: Db) -> LeagueInfo:
    if body.platform != adapter.platform:
        raise HTTPException(status_code=400, detail=f"Unsupported platform {body.platform!r}")
    try:
        info = await adapter.get_league(body.league_id)
    except PlatformNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    repo.upsert_league(db, info)
    db.commit()
    return info


@router.get("/leagues")
def list_leagues(db: Db) -> list[dict]:
    leagues = db.scalars(select(League).order_by(League.name)).all()
    return [
        {
            "league_id": lg.league_id,
            "platform": lg.platform,
            "name": lg.name,
            "season": lg.season,
            "team_count": lg.team_count,
            "league_type": lg.league_type,
            "scoring_preset": lg.scoring_preset,
        }
        for lg in leagues
    ]


@router.get("/leagues/{league_id}/drafts")
async def list_league_drafts(league_id: str, adapter: Adapter, db: Db) -> list[DraftInfo]:
    drafts = await adapter.list_drafts(league_id)
    for draft in drafts:
        repo.upsert_draft(db, draft)
    db.commit()
    return drafts
