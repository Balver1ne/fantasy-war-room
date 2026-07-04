from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String
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
