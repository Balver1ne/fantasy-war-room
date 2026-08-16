"""Pure draft-order math: snake / linear, third-round reversal, traded picks.

No I/O here — this module is the primary unit-test target (DESIGN.md §9).
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DraftOrderConfig:
    team_count: int
    rounds: int
    draft_type: str = "snake"  # "snake" | "linear"
    reversal_round: int = 0  # 0 = none; 3 = third-round reversal
    # draft slot (1-based) -> roster_id; values are None in mock drafts
    slot_to_roster: dict[int, int | None] = field(default_factory=dict)
    # (round, original_roster_id) -> current owner roster_id
    traded: dict[tuple[int, int], int] = field(default_factory=dict)

    @property
    def total_picks(self) -> int:
        return self.team_count * self.rounds


def round_ascends(round_no: int, cfg: DraftOrderConfig) -> bool:
    """Whether draft slots go 1..N (True) or N..1 (False) in this round.

    Snake: odd rounds ascend. Third-round reversal (Sleeper `reversal_round: 3`):
    the direction repeats at the reversal round and alternates after — 1↑ 2↓ 3↓ 4↑ 5↓ …
    Encoded as a parity flip at reversal_round so an empirical correction against a
    real Sleeper 3RR draft is a one-line change.
    """
    if cfg.draft_type == "linear":
        return True
    ascends = round_no % 2 == 1
    if cfg.reversal_round and round_no >= cfg.reversal_round:
        ascends = not ascends
    return ascends


def round_and_index(pick_no: int, cfg: DraftOrderConfig) -> tuple[int, int]:
    """1-based round and 0-based index within the round for a 1-based pick_no."""
    return (pick_no - 1) // cfg.team_count + 1, (pick_no - 1) % cfg.team_count


def slot_for_pick(pick_no: int, cfg: DraftOrderConfig) -> tuple[int, int]:
    """(round, draft_slot 1..N) for a pick number."""
    round_no, idx = round_and_index(pick_no, cfg)
    slot = idx + 1 if round_ascends(round_no, cfg) else cfg.team_count - idx
    return round_no, slot


def owner_of_pick(pick_no: int, cfg: DraftOrderConfig) -> int | None:
    """roster_id that currently owns this pick, after traded-pick remapping.

    None when the slot has no roster mapping (mock drafts) — identify by slot there.
    """
    round_no, slot = slot_for_pick(pick_no, cfg)
    original = cfg.slot_to_roster.get(slot)
    if original is None:
        return None
    return cfg.traded.get((round_no, original), original)


def next_pick_no_for(
    after_pick_no: int,
    cfg: DraftOrderConfig,
    *,
    roster_id: int | None = None,
    slot: int | None = None,
) -> int | None:
    """First pick_no strictly after `after_pick_no` belonging to me.

    Identify by roster_id (trade-aware) in real drafts, or by slot in mock drafts
    (mocks have no roster mapping and no trades). None if I have no remaining picks.
    """
    if roster_id is None and slot is None:
        return None
    for pick_no in range(after_pick_no + 1, cfg.total_picks + 1):
        if roster_id is not None:
            if owner_of_pick(pick_no, cfg) == roster_id:
                return pick_no
        else:
            if slot_for_pick(pick_no, cfg)[1] == slot:
                return pick_no
    return None


def picks_until(
    current_last_pick: int,
    cfg: DraftOrderConfig,
    *,
    roster_id: int | None = None,
    slot: int | None = None,
) -> int | None:
    """How many other picks happen before mine. 0 = I am on the clock."""
    mine = next_pick_no_for(current_last_pick, cfg, roster_id=roster_id, slot=slot)
    if mine is None:
        return None
    return mine - current_last_pick - 1


def format_pick(pick_no: int, cfg: DraftOrderConfig) -> str:
    """Human pick label like '2.03' (round.position-in-round)."""
    round_no, idx = round_and_index(pick_no, cfg)
    return f"{round_no}.{idx + 1:02d}"
