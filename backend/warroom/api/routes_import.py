from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from warroom.api.deps import get_db
from warroom.db import repo
from warroom.db.models import ImportJob, RankingSet
from warroom.ingest import service

router = APIRouter(prefix="/api", tags=["import"])

Db = Annotated[Session, Depends(get_db)]


def _job_or_404(db: Session, job_id: int) -> ImportJob:
    job = db.get(ImportJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"No import job {job_id}")
    return job


def _detail(job: ImportJob) -> dict[str, Any]:
    return {
        **service.job_summary(job),
        "preview": service.preview_rows(job),
        "unmatched": service.unresolved_rows(job),
    }


@router.post("/imports/upload")
async def upload_import(
    db: Db,
    file: UploadFile,
    source: Annotated[str, Form()],
    scoring_format: Annotated[str | None, Form()] = None,
    league_type: Annotated[str, Form()] = "redraft",
) -> dict[str, Any]:
    data = await file.read()
    job = service.build_job_from_upload(
        db, filename=file.filename or "upload", data=data, source=source,
        scoring_format=scoring_format or None, league_type=league_type,
    )
    db.commit()
    return _detail(job)


class PasteRequest(BaseModel):
    text: str
    source: str
    scoring_format: str | None = None
    league_type: str = "redraft"


@router.post("/imports/paste")
def paste_import(body: PasteRequest, db: Db) -> dict[str, Any]:
    job = service.build_job_from_paste(
        db, text=body.text, source=body.source,
        scoring_format=body.scoring_format, league_type=body.league_type,
    )
    db.commit()
    return _detail(job)


@router.get("/imports")
def list_imports(db: Db) -> list[dict[str, Any]]:
    jobs = db.scalars(select(ImportJob).order_by(ImportJob.created_at.desc()).limit(50))
    return [service.job_summary(j) for j in jobs]


@router.get("/imports/{job_id}")
def get_import(job_id: int, db: Db) -> dict[str, Any]:
    return _detail(_job_or_404(db, job_id))


class MappingRequest(BaseModel):
    mappings: dict[str, str]
    scoring_format: str | None = None


@router.put("/imports/{job_id}/mapping")
def update_mapping(job_id: int, body: MappingRequest, db: Db) -> dict[str, Any]:
    job = _job_or_404(db, job_id)
    if body.scoring_format is not None:
        job.scoring_format = body.scoring_format
    problems = service.set_mapping(db, job, body.mappings)
    db.commit()
    return {"problems": problems, **_detail(job)}


@router.post("/imports/{job_id}/match")
def run_match(job_id: int, db: Db) -> dict[str, Any]:
    job = _job_or_404(db, job_id)
    try:
        summary = service.run_matching(db, job)
    except service.IngestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {"summary": summary, **_detail(job)}


class ResolveRequest(BaseModel):
    row_index: int
    sleeper_id: str
    learn_alias: bool = True


@router.post("/imports/{job_id}/resolve")
def resolve(job_id: int, body: ResolveRequest, db: Db) -> dict[str, Any]:
    job = _job_or_404(db, job_id)
    try:
        service.resolve_row(db, job, body.row_index, body.sleeper_id,
                            learn_alias=body.learn_alias)
    except service.IngestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return _detail(job)


class SkipRequest(BaseModel):
    row_index: int


@router.post("/imports/{job_id}/skip")
def skip(job_id: int, body: SkipRequest, db: Db) -> dict[str, Any]:
    job = _job_or_404(db, job_id)
    service.skip_row(db, job, body.row_index)
    db.commit()
    return _detail(job)


class CommitRequest(BaseModel):
    label: str | None = None


@router.post("/imports/{job_id}/commit")
def commit_import(job_id: int, body: CommitRequest, db: Db) -> dict[str, Any]:
    job = _job_or_404(db, job_id)
    try:
        rset = service.commit(db, job, label=body.label)
    except service.IngestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    return {
        "ranking_set_id": rset.id,
        "source": rset.source,
        "kind": rset.kind,
        "scoring_format": rset.scoring_format,
        "row_count": rset.row_count,
    }


@router.get("/players/search")
def player_search(db: Db, q: str, position: str | None = None) -> list[dict[str, Any]]:
    return repo.search_players(db, q, position)


@router.get("/rankings/sets")
def list_ranking_sets(db: Db) -> list[dict[str, Any]]:
    sets = db.scalars(select(RankingSet).order_by(RankingSet.imported_at.desc()))
    return [
        {
            "id": rs.id, "source": rs.source, "kind": rs.kind,
            "scoring_format": rs.scoring_format, "league_type": rs.league_type,
            "label": rs.label, "row_count": rs.row_count, "active": rs.active,
            "imported_at": rs.imported_at.isoformat(),
        }
        for rs in sets
    ]
