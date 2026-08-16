"""Normalized platform DTOs.

Everything outside warroom/platforms/ consumes only these shapes — no vendor payloads.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field

ScoringPreset = Literal["standard", "half_ppr", "ppr"]
LeagueType = Literal["redraft", "dynasty"]
DraftType = Literal["snake", "linear", "auction"]


class PlatformUser(BaseModel):
    platform: str
    user_id: str
    username: str | None = None
    display_name: str | None = None


class LeagueInfo(BaseModel):
    platform: str
    league_id: str
    name: str
    season: str
    team_count: int
    roster_slots: dict[str, int] = Field(default_factory=dict)
    scoring: dict[str, Any] = Field(default_factory=dict)
    scoring_preset: ScoringPreset = "half_ppr"
    league_type: LeagueType = "redraft"
    raw_settings: dict[str, Any] = Field(default_factory=dict)


class DraftInfo(BaseModel):
    platform: str
    draft_id: str
    league_id: str | None = None  # None for Sleeper mock drafts
    draft_type: DraftType = "snake"
    status: str = "pre_draft"
    rounds: int = 0
    team_count: int = 0
    reversal_round: int = 0  # 0 = no reversal; 3 = third-round reversal
    pick_timer: int | None = None
    draft_order: dict[str, int] | None = None  # platform user_id -> draft slot (1-based)
    slot_to_roster: dict[int, int | None] = Field(default_factory=dict)
    raw_settings: dict[str, Any] = Field(default_factory=dict)


class PickInfo(BaseModel):
    pick_no: int
    round: int
    draft_slot: int
    platform_player_id: str
    picked_by: str | None = None
    roster_id: int | None = None
    is_keeper: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class TradedPickInfo(BaseModel):
    season: str
    round: int
    original_roster_id: int
    current_owner_roster_id: int


class PlayerInfo(BaseModel):
    platform_player_id: str
    name: str
    first_name: str | None = None
    last_name: str | None = None
    position: str | None = None
    team: str | None = None
    age: int | None = None
    status: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
