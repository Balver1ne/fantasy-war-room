"""Recommendation engine (DESIGN.md §5).

Pure, unit-testable: (draft_state, ranking_data, preferences, league_settings) →
ranked recommendations with plain-English reasons. No I/O, no platform or DB types.
"""

from warroom.engine.models import (
    DraftState,
    EngineConfig,
    LeagueSettings,
    PlayerMeta,
    Preferences,
    RankingData,
    RankRow,
    Recommendation,
)
from warroom.engine.recommend import recommend

__all__ = [
    "DraftState",
    "EngineConfig",
    "LeagueSettings",
    "PlayerMeta",
    "Preferences",
    "RankingData",
    "RankRow",
    "Recommendation",
    "recommend",
]
