from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON}


class League(Base):
    __tablename__ = "leagues"

    league_id: Mapped[str] = mapped_column(String, primary_key=True)
    platform: Mapped[str] = mapped_column(String, nullable=False, default="sleeper")
    name: Mapped[str] = mapped_column(String, nullable=False)
    season: Mapped[str] = mapped_column(String, nullable=False)
    team_count: Mapped[int] = mapped_column(Integer, nullable=False)
    league_type: Mapped[str] = mapped_column(String, nullable=False, default="redraft")
    scoring_preset: Mapped[str] = mapped_column(String, nullable=False, default="half_ppr")
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    scoring: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Draft(Base):
    __tablename__ = "drafts"

    draft_id: Mapped[str] = mapped_column(String, primary_key=True)
    # Nullable: Sleeper mock drafts have no league.
    league_id: Mapped[str | None] = mapped_column(ForeignKey("leagues.league_id"), nullable=True)
    platform: Mapped[str] = mapped_column(String, nullable=False, default="sleeper")
    type: Mapped[str] = mapped_column(String, nullable=False, default="snake")
    status: Mapped[str] = mapped_column(String, nullable=False, default="pre_draft")
    rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    team_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reversal_round: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pick_timer: Mapped[int | None] = mapped_column(Integer, nullable=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    draft_order: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    slot_to_roster: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Player(Base):
    __tablename__ = "players"

    sleeper_id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    name_normalized: Mapped[str] = mapped_column(String, nullable=False, index=True)
    position: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    team: Mapped[str | None] = mapped_column(String, nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DraftPick(Base):
    __tablename__ = "draft_picks"

    draft_id: Mapped[str] = mapped_column(ForeignKey("drafts.draft_id"), primary_key=True)
    pick_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    sleeper_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    draft_slot: Mapped[int] = mapped_column(Integer, nullable=False)
    roster_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    picked_by: Mapped[str | None] = mapped_column(String, nullable=True)
    is_keeper: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Meta(Base):
    __tablename__ = "meta"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --- Phase 2: ingestion + matching -----------------------------------------
# New tables are additive, so create_all extends the schema safely (CLAUDE.md).


class RankingSet(Base):
    """An immutable versioned import from one source. Re-importing a source creates a
    new set; the engine uses the most recent active set per (source, scoring_format)."""

    __tablename__ = "ranking_sets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String, nullable=False, default="rankings")  # rankings|adp
    scoring_format: Mapped[str] = mapped_column(String, nullable=False)  # standard|half_ppr|ppr
    league_type: Mapped[str] = mapped_column(String, nullable=False, default="redraft")
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    source_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Ranking(Base):
    __tablename__ = "rankings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ranking_set_id: Mapped[int] = mapped_column(
        ForeignKey("ranking_sets.id"), nullable=False, index=True
    )
    sleeper_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    projection: Mapped[float | None] = mapped_column(Float, nullable=True)
    tier: Mapped[int | None] = mapped_column(Integer, nullable=True)
    position_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    adp: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)


class PlayerAlias(Base):
    """Manual + learned name→player resolutions, so a match never has to be repeated
    (DESIGN.md §3). Checked before fuzzy matching."""

    __tablename__ = "player_aliases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alias_normalized: Mapped[str] = mapped_column(String, nullable=False, index=True)
    sleeper_id: Mapped[str] = mapped_column(String, nullable=False)
    source: Mapped[str | None] = mapped_column(String, nullable=True)  # None = manual
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FlagType(Base):
    """User-extensible flag declarations (Fantasy Headliners signals + user-defined)."""

    __tablename__ = "flag_types"

    flag_name: Mapped[str] = mapped_column(String, primary_key=True)
    value_kind: Mapped[str] = mapped_column(String, nullable=False)  # bool|numeric
    tiebreak_priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    optional_score_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlayerFlag(Base):
    __tablename__ = "player_flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sleeper_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    flag_name: Mapped[str] = mapped_column(ForeignKey("flag_types.flag_name"), nullable=False)
    value_bool: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    value_num: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    ranking_set_id: Mapped[int | None] = mapped_column(
        ForeignKey("ranking_sets.id"), nullable=True
    )
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImportPreset(Base):
    """Saved column/flag mappings + PDF extraction config per source layout, so repeat
    imports are near-zero-click (DESIGN.md §4)."""

    __tablename__ = "import_presets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, nullable=False, index=True)
    layout_fingerprint: Mapped[str] = mapped_column(String, nullable=False, index=True)
    file_kind: Mapped[str] = mapped_column(String, nullable=False, default="csv")  # csv|pdf
    mappings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    pdf_extraction_config: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImportJob(Base):
    """A staged import awaiting column mapping / unmatched resolution before it is
    committed to an immutable ranking_set. Holds the raw parsed rows and mapping."""

    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    file_kind: Mapped[str] = mapped_column(String, nullable=False, default="csv")
    scoring_format: Mapped[str | None] = mapped_column(String, nullable=True)
    league_type: Mapped[str] = mapped_column(String, nullable=False, default="redraft")
    source_filename: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="mapping")
    # mapping | resolving | committed
    columns: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # detected headers
    mappings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # column -> field/flag
    raw_rows: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # {"rows": [...]}
    matches: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # row_id -> resolution
    ranking_set_id: Mapped[int | None] = mapped_column(
        ForeignKey("ranking_sets.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
