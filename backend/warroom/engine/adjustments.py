"""5.3 Live adjustments recomputed each pick: roster need and positional runs.

(Tier-cliff scarcity lives in consensus.tier_value_drop; survival in survival.py.)
"""

import math

from warroom.engine.models import EngineConfig, LeagueSettings

# How much bench depth past the startable need is still worth drafting, per position.
_DEPTH = {"QB": 1, "RB": 3, "WR": 4, "TE": 1, "K": 0, "DEF": 0}


def effective_need(position: str, league: LeagueSettings, config: EngineConfig) -> float:
    return (
        league.starters.get(position, 0)
        + config.flex_split.get(position, 0.0) * league.flex
        + config.superflex_split.get(position, 0.0) * league.superflex
    )


def roster_need_multiplier(
    position: str, have: int, league: LeagueSettings, config: EngineConfig
) -> float:
    """1.0 while a starting slot is unfilled, then diminishing returns per extra body,
    with a hard cap so the engine never pushes a pointless 4th QB or an early K/DEF."""
    need = effective_need(position, league, config)
    cap = math.ceil(need) + _DEPTH.get(position, 2)

    if position in config.hard_cap_positions and have >= league.starters.get(position, 1):
        return 0.02
    if have >= cap:
        return 0.02
    if have < need:
        return 1.0
    surplus = have - need
    return config.need_fill_decay ** (surplus + 1)


def run_boost(position: str, recent_positions: list[str], config: EngineConfig) -> float:
    """Additive urgency when a position is running: ≥ threshold of the last window's
    picks share the position (DESIGN.md §5.3)."""
    window = recent_positions[-config.run_window:]
    count = window.count(position)
    if count >= config.run_threshold:
        return config.run_boost_per_pick * count
    return 0.0


def count_positions(sids: list[str], player_position) -> dict[str, int]:
    counts: dict[str, int] = {}
    for sid in sids:
        pos = player_position(sid)
        if pos:
            counts[pos] = counts.get(pos, 0) + 1
    return counts
