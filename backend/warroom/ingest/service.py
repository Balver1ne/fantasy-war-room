"""Import service: parse → map → match → resolve → commit an immutable ranking_set.

Staged in an ImportJob so unmatched rows can be resolved before anything touches the
board. The design doc is emphatic: never silently ingest a mismatch (DESIGN.md §3, §4).
"""

from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from warroom.db import repo
from warroom.db.models import (
    FlagType,
    ImportJob,
    PlayerFlag,
    Ranking,
    RankingSet,
)
from warroom.ingest import csv_parse, pdf_extract
from warroom.ingest import mapping as mapping_mod
from warroom.ingest.values import to_bool, to_float, to_int
from warroom.matching.engine import MatchIndex
from warroom.matching.normalize import position_rank_from
from warroom.names import normalize_name


class IngestError(Exception):
    pass


def _candidate_dicts(candidates) -> list[dict[str, Any]]:
    return [
        {"sleeper_id": c.sleeper_id, "name": c.name, "position": c.position,
         "team": c.team, "score": round(c.score, 1)}
        for c in candidates
    ]


def create_job(
    session: Session,
    *,
    source: str,
    headers: list[str],
    rows: list[dict[str, str]],
    scoring_format: str | None = None,
    league_type: str = "redraft",
    file_kind: str = "csv",
    source_filename: str | None = None,
    initial_mapping: dict[str, str] | None = None,
    raw_text: str = "",
    layout: str | None = None,
    notes: list[str] | None = None,
) -> ImportJob:
    job = ImportJob(
        source=source,
        file_kind=file_kind,
        scoring_format=scoring_format,
        league_type=league_type,
        source_filename=source_filename,
        status="mapping",
        columns={
            "headers": headers,
            "raw_text": raw_text[:8000],
            "layout": layout,
            "notes": notes or [],
        },
        mappings=initial_mapping or mapping_mod.auto_map(headers),
        raw_rows={"rows": rows},
        matches={},
    )
    session.add(job)
    session.flush()
    return job


def build_job_from_upload(
    session: Session,
    *,
    filename: str,
    data: bytes,
    source: str,
    scoring_format: str | None,
    league_type: str = "redraft",
) -> ImportJob:
    """Dispatch on file type: PDFs go through the text extractor (carrying their
    suggested mapping + raw text for the mandatory preview); CSVs are parsed directly."""
    if filename.lower().endswith(".pdf"):
        ex = pdf_extract.extract(data)
        return create_job(
            session, source=source, headers=ex.headers, rows=ex.rows,
            scoring_format=scoring_format, league_type=league_type, file_kind="pdf",
            source_filename=filename, initial_mapping=ex.suggested_mapping,
            raw_text=ex.raw_text, layout=ex.layout, notes=ex.notes,
        )
    headers, rows = csv_parse.parse_csv(csv_parse.decode_bytes(data))
    return create_job(
        session, source=source, headers=headers, rows=rows,
        scoring_format=scoring_format, league_type=league_type, file_kind="csv",
        source_filename=filename,
    )


def build_job_from_paste(
    session: Session,
    *,
    text: str,
    source: str,
    scoring_format: str | None,
    league_type: str = "redraft",
) -> ImportJob:
    """Paste fallback for PDFs that parse badly (DESIGN.md §4): treat pasted content as
    delimited text through the CSV parser."""
    headers, rows = csv_parse.parse_csv(text)
    return create_job(
        session, source=source, headers=headers, rows=rows,
        scoring_format=scoring_format, league_type=league_type, file_kind="paste",
        source_filename=None,
    )


def preview_rows(job: ImportJob, limit: int = 25) -> list[dict[str, str]]:
    return job.raw_rows.get("rows", [])[:limit]


def job_summary(job: ImportJob) -> dict[str, Any]:
    matches = job.matches or {}
    matched = sum(1 for e in matches.values() if e.get("status") == "matched")
    skipped = sum(1 for e in matches.values() if e.get("status") == "skipped")
    cols = job.columns or {}
    return {
        "id": job.id,
        "source": job.source,
        "file_kind": job.file_kind,
        "scoring_format": job.scoring_format,
        "league_type": job.league_type,
        "source_filename": job.source_filename,
        "status": job.status,
        "headers": cols.get("headers", []),
        "mappings": job.mappings,
        "layout": cols.get("layout"),
        "notes": cols.get("notes", []),
        "raw_text": cols.get("raw_text", ""),
        "row_count": len(job.raw_rows.get("rows", [])),
        "matched": matched,
        "skipped": skipped,
        "unresolved": len(unresolved_rows(job)),
        "ranking_set_id": job.ranking_set_id,
    }


def set_mapping(session: Session, job: ImportJob, mappings: dict[str, str]) -> list[str]:
    problems = mapping_mod.validate_mapping(mappings)
    job.mappings = dict(mappings)
    session.flush()
    return problems


def _field_columns(mappings: dict[str, str]) -> dict[str, str]:
    """field -> header (for canonical fields only)."""
    out: dict[str, str] = {}
    for header, target in mappings.items():
        if target and target != "ignore" and not target.startswith("flag:"):
            out[target] = header
    return out


def run_matching(session: Session, job: ImportJob) -> dict[str, Any]:
    """Match every row against the current player universe; store the result on the job.

    Returns a summary {total, matched, unmatched}. Rows already resolved manually keep
    their resolution.
    """
    problems = mapping_mod.validate_mapping(job.mappings)
    if problems:
        raise IngestError("; ".join(problems))

    index = MatchIndex(repo.load_player_refs(session), repo.load_aliases(session))
    fields = _field_columns(job.mappings)
    name_col = fields["name"]
    rows = job.raw_rows["rows"]
    matches = dict(job.matches)
    matched = 0

    for i, row in enumerate(rows):
        key = str(i)
        prior = matches.get(key)
        if prior and prior.get("resolved"):
            matched += 1
            continue
        name = row.get(name_col, "").strip()
        team = row.get(fields["team"], "").strip() if "team" in fields else None
        position = row.get(fields["position"], "").strip() if "position" in fields else None
        if not name:
            matches[key] = {"status": "unmatched", "reason": "no name", "name": "",
                            "candidates": []}
            continue
        result = index.match(name, position, team)
        matches[key] = {
            "status": "matched" if result.matched else result.method,
            "sleeper_id": result.sleeper_id,
            "method": result.method,
            "score": round(result.score, 1),
            "name": name,
            "team": team,
            "position": position,
            "candidates": _candidate_dicts(result.candidates),
            "resolved": False,
        }
        if result.matched:
            matched += 1

    job.matches = matches
    job.status = "resolving"
    session.flush()
    return {"total": len(rows), "matched": matched, "unmatched": len(rows) - matched}


def resolve_row(
    session: Session,
    job: ImportJob,
    row_index: int,
    sleeper_id: str,
    *,
    learn_alias: bool = True,
) -> None:
    """Manually attach a Sleeper player to a row; persist a learned alias so this name
    never has to be resolved again."""
    key = str(row_index)
    entry = dict(job.matches.get(key, {}))
    if not entry:
        raise IngestError(f"No row {row_index} in job {job.id}")
    entry["sleeper_id"] = sleeper_id
    entry["status"] = "matched"
    entry["method"] = "manual"
    entry["resolved"] = True
    matches = dict(job.matches)
    matches[key] = entry
    job.matches = matches
    if learn_alias and entry.get("name"):
        repo.add_alias(session, normalize_name(entry["name"]), sleeper_id, job.source)
    session.flush()


def skip_row(session: Session, job: ImportJob, row_index: int) -> None:
    key = str(row_index)
    entry = dict(job.matches.get(key, {}))
    entry["status"] = "skipped"
    entry["resolved"] = True
    entry["sleeper_id"] = None
    matches = dict(job.matches)
    matches[key] = entry
    job.matches = matches
    session.flush()


def unresolved_rows(job: ImportJob) -> list[dict[str, Any]]:
    out = []
    for key, entry in job.matches.items():
        if entry.get("status") not in ("matched", "skipped"):
            out.append({"row_index": int(key), **entry})
    return sorted(out, key=lambda e: e["row_index"])


def commit(session: Session, job: ImportJob, *, label: str | None = None) -> RankingSet:
    """Freeze the job into an immutable ranking_set + rankings + flags.

    Requires a scoring format (no untagged imports) and every row matched or skipped.
    """
    if not job.scoring_format:
        raise IngestError("scoring_format is required before commit (no untagged imports)")
    outstanding = unresolved_rows(job)
    if outstanding:
        raise IngestError(f"{len(outstanding)} rows still unresolved")

    fields = _field_columns(job.mappings)
    flag_cols: dict[str, tuple[str, str]] = {}  # header -> (flag_name, kind)
    for header, target in job.mappings.items():
        spec = mapping_mod.parse_flag(target) if target else None
        if spec:
            flag_cols[header] = spec

    # deactivate prior active sets of the same identity
    prior = session.scalars(
        select(RankingSet).where(
            RankingSet.source == job.source,
            RankingSet.scoring_format == job.scoring_format,
            RankingSet.kind == ("adp" if _is_adp(fields) else "rankings"),
            RankingSet.active.is_(True),
        )
    ).all()
    for ps in prior:
        ps.active = False

    rset = RankingSet(
        source=job.source,
        kind="adp" if _is_adp(fields) else "rankings",
        scoring_format=job.scoring_format,
        league_type=job.league_type,
        label=label,
        source_filename=job.source_filename,
        active=True,
    )
    session.add(rset)
    session.flush()

    # ensure flag types exist
    for _header, (flag_name, kind) in flag_cols.items():
        if session.get(FlagType, flag_name) is None:
            session.add(FlagType(flag_name=flag_name, value_kind=kind))

    rows = job.raw_rows["rows"]
    count = 0
    for key, entry in job.matches.items():
        if entry.get("status") != "matched" or not entry.get("sleeper_id"):
            continue
        row = rows[int(key)]
        sid = entry["sleeper_id"]
        pos_token = row.get(fields["position"], "") if "position" in fields else ""
        session.add(
            Ranking(
                ranking_set_id=rset.id,
                sleeper_id=sid,
                rank=to_int(row.get(fields["rank"])) if "rank" in fields else None,
                projection=(
                    to_float(row.get(fields["projection"])) if "projection" in fields else None
                ),
                tier=to_int(row.get(fields["tier"])) if "tier" in fields else None,
                position_rank=(
                    to_int(row.get(fields["position_rank"])) if "position_rank" in fields
                    else position_rank_from(pos_token)
                ),
                adp=to_float(row.get(fields["adp"])) if "adp" in fields else None,
                notes=row.get(fields["notes"]) if "notes" in fields else None,
            )
        )
        for header, (flag_name, kind) in flag_cols.items():
            raw = row.get(header)
            if raw is None or str(raw).strip() == "":
                continue
            session.add(
                PlayerFlag(
                    sleeper_id=sid,
                    flag_name=flag_name,
                    value_bool=to_bool(raw) if kind == "bool" else None,
                    value_num=to_float(raw) if kind in ("numeric", "rating") else None,
                    source=job.source,
                    ranking_set_id=rset.id,
                )
            )
        count += 1

    rset.row_count = count
    job.status = "committed"
    job.ranking_set_id = rset.id
    session.flush()
    return rset


def _is_adp(fields: dict[str, str]) -> bool:
    """An import whose primary numeric column is ADP is stored as an adp set."""
    return "adp" in fields and "rank" not in fields


def delete_ranking_set(session: Session, set_id: int) -> dict[str, Any] | None:
    """Remove a ranking set and everything tied to it (rankings + flags). If it was the
    active version of its source, the most recent remaining version is reactivated so a
    source is never left with only inactive sets. Returns None if the set doesn't exist."""
    rset = session.get(RankingSet, set_id)
    if rset is None:
        return None
    source, scoring, kind, was_active = rset.source, rset.scoring_format, rset.kind, rset.active
    session.execute(delete(Ranking).where(Ranking.ranking_set_id == set_id))
    session.execute(delete(PlayerFlag).where(PlayerFlag.ranking_set_id == set_id))
    session.execute(
        update(ImportJob).where(ImportJob.ranking_set_id == set_id).values(ranking_set_id=None)
    )
    session.delete(rset)
    session.flush()

    reactivated: int | None = None
    if was_active:
        replacement = session.scalars(
            select(RankingSet)
            .where(RankingSet.source == source, RankingSet.scoring_format == scoring,
                   RankingSet.kind == kind)
            .order_by(RankingSet.imported_at.desc())
        ).first()
        if replacement is not None:
            replacement.active = True
            reactivated = replacement.id
        session.flush()
    return {"deleted": set_id, "reactivated": reactivated}
