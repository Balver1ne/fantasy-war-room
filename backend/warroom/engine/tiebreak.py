"""5.4 Tiebreaker layer: when composites are within epsilon, Fantasy Headliners flags
break the tie by user-assigned priority; if flags don't differentiate, the player less
likely to survive to the next pick wins.
"""

from dataclasses import dataclass

from warroom.engine.models import EngineConfig, RankingData


@dataclass
class Scored:
    sleeper_id: str
    composite: float
    survival: float | None


def flag_key(sid: str, data: RankingData) -> tuple[float, ...]:
    """Values of this player's flags in descending priority order (booleans as 1/0),
    so a lexicographic compare implements 'highest-priority flag wins, then next'."""
    order = sorted(data.flag_priority, key=lambda f: data.flag_priority[f], reverse=True)
    player_flags = data.flags.get(sid, {})
    key: list[float] = []
    for flag in order:
        val = player_flags.get(flag)
        if isinstance(val, bool):
            key.append(1.0 if val else 0.0)
        elif isinstance(val, (int, float)):
            key.append(float(val))
        else:
            key.append(0.0)
    return tuple(key)


def _within(a: float, b: float, epsilon: float) -> bool:
    scale = max(abs(a), abs(b), 1e-9)
    return abs(a - b) <= epsilon * scale


def order_with_tiebreaks(
    scored: list[Scored], data: RankingData, config: EngineConfig
) -> list[str]:
    """Sort by composite desc, then reorder each near-tie cluster by flag priority and,
    failing that, by lower survival probability (take him or lose him)."""
    scored = sorted(scored, key=lambda s: s.composite, reverse=True)
    result: list[str] = []
    i = 0
    n = len(scored)
    while i < n:
        j = i + 1
        top = scored[i].composite
        while j < n and _within(top, scored[j].composite, config.tie_epsilon):
            j += 1
        cluster = scored[i:j]
        if len(cluster) > 1:
            cluster.sort(
                key=lambda s: (
                    tuple(-v for v in flag_key(s.sleeper_id, data)),
                    s.survival if s.survival is not None else 2.0,
                )
            )
        result.extend(s.sleeper_id for s in cluster)
        i = j
    return result


def tie_edge(sid: str, other: str, data: RankingData) -> str | None:
    """The flag name that decides a tie between two players, for the reason string."""
    order = sorted(data.flag_priority, key=lambda f: data.flag_priority[f], reverse=True)
    a, b = data.flags.get(sid, {}), data.flags.get(other, {})
    for flag in order:
        av = a.get(flag)
        bv = b.get(flag)
        an = 1.0 if av is True else (float(av) if isinstance(av, (int, float)) else 0.0)
        bn = 1.0 if bv is True else (float(bv) if isinstance(bv, (int, float)) else 0.0)
        if an > bn:
            return flag
    return None
