"""5.2 League-adjusted value (VBD).

Replacement level per position = the value of the last startable player at that position
across the league (team_count × starters, including the league's FLEX and SUPERFLEX
allocation). Value Over Replacement = blended value − that baseline. SUPERFLEX pushes the
QB replacement deeper, which automatically elevates QB value.
"""

from warroom.engine.consensus import value_from_rank
from warroom.engine.models import EngineConfig, LeagueSettings, RankingData


def replacement_index(position: str, league: LeagueSettings, config: EngineConfig) -> int:
    """How many players at this position are 'startable' league-wide (1-based depth)."""
    starters = league.starters.get(position, 0)
    flex_share = config.flex_split.get(position, 0.0) * league.flex
    sflex_share = config.superflex_split.get(position, 0.0) * league.superflex
    per_team = starters + flex_share + sflex_share
    return max(1, round(per_team * league.team_count))


def replacement_values(
    blended: dict[str, float],
    data: RankingData,
    league: LeagueSettings,
    config: EngineConfig,
) -> dict[str, float]:
    """Baseline value at each position. If the pool is shallower than the replacement
    depth, extrapolate down the value curve so deep positions aren't over-credited."""
    by_pos: dict[str, list[float]] = {}
    for sid, value in blended.items():
        meta = data.players.get(sid)
        if meta:
            by_pos.setdefault(meta.position, []).append(value)

    baselines: dict[str, float] = {}
    for pos, values in by_pos.items():
        values.sort(reverse=True)
        idx = replacement_index(pos, league, config)
        if idx <= len(values):
            baselines[pos] = values[idx - 1]
        elif values:
            # fewer ranked players than startable depth — extend the curve past the pool
            tail_rank = idx
            baselines[pos] = min(values[-1], value_from_rank(tail_rank, config.value_half_life))
        else:
            baselines[pos] = 0.0
    return baselines


def value_over_replacement(
    blended: dict[str, float],
    data: RankingData,
    baselines: dict[str, float],
) -> dict[str, float]:
    vor: dict[str, float] = {}
    for sid, value in blended.items():
        meta = data.players.get(sid)
        if meta is None:
            continue
        vor[sid] = value - baselines.get(meta.position, 0.0)
    return vor
