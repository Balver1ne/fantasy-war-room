"""5.5 Plain-English reasons — at most 3 bullets, most decision-relevant first.

"A number with no explanation gets ignored at pick 6 of a 90-second clock."
"""

from warroom.engine.models import DraftState, EngineConfig, Preferences, RankingData
from warroom.engine.tiebreak import tie_edge


def build_reasons(
    sid: str,
    info: dict,
    draft_state: DraftState,
    preferences: Preferences,
    data: RankingData,
    config: EngineConfig,
    needs: dict[str, int],
    order: list[str],
    comp_by_sid: dict[str, float],
) -> list[str]:
    pos = info["pos"]
    reasons: list[str] = []

    note = preferences.notes.get(sid)
    if note:
        reasons.append(f'Your note: "{note}"')

    if preferences.my_guys.get(sid):
        reasons.append("Your target (My Guys)")

    drop = info.get("drop")
    if drop is not None and drop > config.tier_gap_threshold and info.get("tier"):
        reasons.append(
            f"Last tier-{info['tier']} {pos} left; next {pos} tier is a "
            f"{drop:.0f}-pt value drop"
        )

    window = draft_state.recent_positions[-config.run_window:]
    run_count = window.count(pos)
    if run_count >= config.run_threshold:
        reasons.append(f"{run_count} of last {len(window)} picks were {pos} - run in progress")

    if needs.get(pos, 0) > 0:
        reasons.append(f"Fills an open {pos} starter slot")

    survival = info.get("survival")
    if survival is not None and survival < 0.5:
        if draft_state.my_next_pick_label:
            label = draft_state.my_next_pick_label
        elif draft_state.my_next_pick_no:
            label = f"pick {draft_state.my_next_pick_no}"
        else:
            label = "your next pick"
        reasons.append(f"{survival * 100:.0f}% chance he's back at {label}")

    # tie edge over the next player in the final order
    idx = order.index(sid) if sid in order else -1
    if 0 <= idx < len(order) - 1:
        nxt = order[idx + 1]
        a, b = comp_by_sid.get(sid, 0.0), comp_by_sid.get(nxt, 0.0)
        if abs(a - b) <= config.tie_epsilon * max(abs(a), abs(b), 1e-9):
            edge = tie_edge(sid, nxt, data)
            if edge:
                other = data.players.get(nxt)
                who = other.name.split()[-1] if other else "next"
                reasons.append(f"Tied on value with {who} - edge: FH {edge} flag")

    return reasons[:3]
