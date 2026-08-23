"""5.5 Orchestrator: assemble the ranked recommendations with reasons.

composite = (VOR + My-Guys boost) × roster-need multiplier × (1 + run + tier-cliff),
then near-ties are broken by FH flags and survival probability. Do-Not-Draft players
are excluded outright; drafted players are removed every pick.
"""

from time import perf_counter

from warroom.engine import adjustments, consensus, reasons, survival, tiebreak, vbd
from warroom.engine.models import (
    FLEX_POSITIONS,
    DraftState,
    EngineConfig,
    LeagueSettings,
    Preferences,
    RankingData,
    Recommendation,
    RecommendationResult,
)


def _needs(my_counts: dict[str, int], league: LeagueSettings) -> dict[str, int]:
    needs: dict[str, int] = {}
    for pos, count in league.starters.items():
        unfilled = max(0, count - my_counts.get(pos, 0))
        if unfilled:
            needs[pos] = unfilled
    if league.flex:
        surplus = sum(
            max(0, my_counts.get(p, 0) - league.starters.get(p, 0)) for p in FLEX_POSITIONS
        )
        flex_unfilled = max(0, league.flex - surplus)
        if flex_unfilled:
            needs["FLEX"] = flex_unfilled
    return needs


def recommend(
    draft_state: DraftState,
    data: RankingData,
    preferences: Preferences,
    league: LeagueSettings,
    config: EngineConfig | None = None,
) -> RecommendationResult:
    config = config or EngineConfig()
    t0 = perf_counter()

    blended = consensus.blend_values(data, config)
    tiers = consensus.position_tiers(blended, data, config, preferences.tier_overrides)
    baselines = vbd.replacement_values(blended, data, league, config)
    vor = vbd.value_over_replacement(blended, data, baselines)

    available = [
        sid
        for sid in blended
        if sid not in draft_state.drafted
        and sid not in preferences.do_not_draft
        and sid in data.players
    ]
    available_set = set(available)

    def pos_of(sid: str) -> str | None:
        meta = data.players.get(sid)
        return meta.position if meta else None

    my_counts = adjustments.count_positions(draft_state.my_roster, pos_of)
    needs = _needs(my_counts, league)

    scored: list[tiebreak.Scored] = []
    info_by_sid: dict[str, dict] = {}
    for sid in available:
        pos = data.players[sid].position
        base = vor.get(sid, 0.0)
        my_guy = preferences.my_guys.get(sid, 0.0) * config.my_guy_tier_value
        need_mult = adjustments.roster_need_multiplier(pos, my_counts.get(pos, 0), league, config)
        run_b = adjustments.run_boost(pos, draft_state.recent_positions, config)
        drop = consensus.tier_value_drop(sid, available_set, blended, tiers, data)
        at_cliff = drop is not None and drop > config.tier_gap_threshold
        cliff_b = config.cliff_boost if at_cliff else 0.0
        surv = survival.prob_available(
            data.adp.get(sid), draft_state.my_next_pick_no, survival.sigma_for(pos, config)
        )
        composite = (base + my_guy) * need_mult * (1.0 + run_b + cliff_b)
        # An over-rostered / hard-capped position must sink below any genuinely useful
        # player, even a below-replacement one — never surface a pointless extra QB/K/DEF.
        if need_mult <= 0.021:
            composite -= config.over_cap_penalty
        scored.append(tiebreak.Scored(sid, composite, surv))
        info_by_sid[sid] = {
            "base": base, "pos": pos, "tier": tiers.get(sid), "drop": drop, "survival": surv,
        }

    order = tiebreak.order_with_tiebreaks(scored, data, config)
    comp_by_sid = {s.sleeper_id: s.composite for s in scored}

    recs: list[Recommendation] = []
    for sid in order[: config.top_n]:
        meta = data.players[sid]
        info = info_by_sid[sid]
        recs.append(
            Recommendation(
                sleeper_id=sid,
                name=meta.name,
                position=meta.position,
                team=meta.team,
                composite_score=round(comp_by_sid[sid], 2),
                base_vor=round(info["base"], 2),
                tier=info["tier"],
                survival_prob=(
                    round(info["survival"], 3) if info["survival"] is not None else None
                ),
                flags=sorted(data.flags.get(sid, {}).keys()),
                reasons=reasons.build_reasons(
                    sid, info, draft_state, preferences, data, config, needs, order, comp_by_sid
                ),
            )
        )

    return RecommendationResult(
        recommendations=recs, needs=needs, compute_ms=(perf_counter() - t0) * 1000.0
    )
