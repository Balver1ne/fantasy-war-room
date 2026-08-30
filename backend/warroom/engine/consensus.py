"""5.1 Consensus value: rank → value curve, weighted blend, gap-detection tiers.

We blend *values*, not raw ranks — averaging ranks compresses the large gaps at the top
of the board (the difference between the 1st and 5th player dwarfs 100th vs 104th). The
value curve is a rank half-life decay, so equal rank steps are worth more near the top.
"""

from warroom.engine.models import EngineConfig, RankingData


def value_from_rank(rank: int, half_life: float) -> float:
    """0–100 value for an overall rank. rank 1 → 100; each `half_life` ranks halves it."""
    return 100.0 * 0.5 ** ((rank - 1) / half_life)


def blend_values(data: RankingData, config: EngineConfig) -> dict[str, float]:
    """Weighted average of each source's rank-derived value, over the sources that rank
    the player. Projection, when a source provides one, is used directly (normalized to
    the same 0–100 scale within that source)."""
    proj_max: dict[str, float] = {}
    for source, rows in data.sources.items():
        projs = [r.projection for r in rows.values() if r.projection]
        if projs:
            proj_max[source] = max(projs)

    hl = config.value_half_life
    # Pass 1: contributions from sources that give an overall rank or a projection.
    # Position-only contributions are deferred — they need the consensus to anchor to.
    num: dict[str, float] = {}
    den: dict[str, float] = {}
    deferred: list[tuple[str, float, int]] = []  # (sid, weight, position_rank)
    for sid in data.players:
        for source, rows in data.sources.items():
            row = rows.get(sid)
            if row is None:
                continue
            weight = data.weights.get(source, 1.0)
            if row.projection is not None and proj_max.get(source):
                value = 100.0 * row.projection / proj_max[source]
            elif row.rank is not None:
                value = value_from_rank(row.rank, hl)
            elif row.position_rank is not None:
                deferred.append((sid, weight, row.position_rank))
                continue
            else:
                continue
            num[sid] = num.get(sid, 0.0) + weight * value
            den[sid] = den.get(sid, 0.0) + weight

    # Anchor position-only sources: a source's "RB5" is worth what the 5th-best RB is
    # worth on the consensus board so far. Keeps every source on one 0–100 scale, and is
    # a no-op when no source is position-only (Pass 1 already holds the full blend).
    if deferred:
        prelim = {sid: num[sid] / den[sid] for sid in den}
        by_pos: dict[str, list[float]] = {}
        for sid, value in prelim.items():
            meta = data.players.get(sid)
            if meta:
                by_pos.setdefault(meta.position, []).append(value)
        for vals in by_pos.values():
            vals.sort(reverse=True)
        for sid, weight, prk in deferred:
            meta = data.players.get(sid)
            vals = by_pos.get(meta.position, []) if meta else []
            if vals:
                value = vals[min(prk, len(vals)) - 1]
            else:  # position has no rank-based consensus — fall back to the raw curve
                value = value_from_rank(prk, hl)
            num[sid] = num.get(sid, 0.0) + weight * value
            den[sid] = den.get(sid, 0.0) + weight

    return {sid: num[sid] / den[sid] for sid in den if den[sid] > 0}


def consensus_rank(blended: dict[str, float]) -> dict[str, int]:
    order = sorted(blended, key=lambda s: blended[s], reverse=True)
    return {sid: i + 1 for i, sid in enumerate(order)}


def position_tiers(
    blended: dict[str, float],
    data: RankingData,
    config: EngineConfig,
    tier_overrides: dict[str, int] | None = None,
) -> dict[str, int]:
    """Per-position tiers from gaps in the blended value curve: a drop larger than the
    configured threshold starts a new tier."""
    tiers: dict[str, int] = {}
    by_pos: dict[str, list[str]] = {}
    for sid in blended:
        meta = data.players.get(sid)
        if meta:
            by_pos.setdefault(meta.position, []).append(sid)

    for _pos, sids in by_pos.items():
        sids.sort(key=lambda s: blended[s], reverse=True)
        tier = 1
        prev: float | None = None
        for sid in sids:
            value = blended[sid]
            if prev is not None and prev - value > config.tier_gap_threshold:
                tier += 1
            tiers[sid] = tier
            prev = value

    for sid, forced in (tier_overrides or {}).items():
        tiers[sid] = forced
    return tiers


def tier_value_drop(
    sid: str,
    available: set[str],
    blended: dict[str, float],
    tiers: dict[str, int],
    data: RankingData,
) -> float | None:
    """Value gap between this player and the best available player in the next tier at
    his position — the size of the cliff if he's taken. None if no next tier remains."""
    meta = data.players.get(sid)
    if meta is None or sid not in tiers:
        return None
    my_tier = tiers[sid]
    my_value = blended.get(sid, 0.0)
    next_vals = [
        blended[o]
        for o in available
        if o != sid
        and data.players.get(o)
        and data.players[o].position == meta.position
        and tiers.get(o, my_tier) > my_tier
    ]
    if not next_vals:
        return None
    return my_value - max(next_vals)
