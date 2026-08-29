"""Engine input/output types + tunable configuration. Plain dataclasses, no I/O."""

from dataclasses import dataclass, field

FLEX_POSITIONS = ("RB", "WR", "TE")


@dataclass(frozen=True)
class PlayerMeta:
    sleeper_id: str
    name: str
    position: str
    team: str | None = None


@dataclass(frozen=True)
class RankRow:
    rank: int | None = None            # overall rank in this source
    position_rank: int | None = None
    projection: float | None = None


@dataclass
class RankingData:
    """Everything the engine needs about players, from the ingested ranking sets."""

    players: dict[str, PlayerMeta] = field(default_factory=dict)
    # source name -> {sleeper_id -> RankRow}
    sources: dict[str, dict[str, RankRow]] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)          # source -> weight
    adp: dict[str, float] = field(default_factory=dict)              # sleeper_id -> ADP
    flags: dict[str, dict[str, float | bool]] = field(default_factory=dict)
    flag_priority: dict[str, int] = field(default_factory=dict)      # flag_name -> priority
    flag_kinds: dict[str, str] = field(default_factory=dict)         # flag_name -> kind


@dataclass
class LeagueSettings:
    team_count: int
    starters: dict[str, int] = field(default_factory=dict)  # QB/RB/WR/TE/K/DEF -> count
    flex: int = 0            # RB/WR/TE flex slots
    superflex: int = 0       # QB-eligible flex slots
    scoring_preset: str = "half_ppr"


@dataclass
class Preferences:
    my_guys: dict[str, float] = field(default_factory=dict)      # sleeper_id -> tiers of boost
    do_not_draft: set[str] = field(default_factory=set)
    tier_overrides: dict[str, int] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)


@dataclass
class DraftState:
    drafted: set[str] = field(default_factory=set)
    my_roster: list[str] = field(default_factory=list)          # sleeper_ids I hold
    recent_positions: list[str] = field(default_factory=list)   # last picks, oldest→newest
    current_pick_no: int = 0
    my_next_pick_no: int | None = None
    my_next_pick_label: str | None = None                       # e.g. "3.08"


@dataclass
class EngineConfig:
    value_half_life: float = 24.0        # ranks to halve the value curve (top-end preserved)
    tier_gap_threshold: float = 5.0      # value drop that starts a new tier
    flex_split: dict[str, float] = field(
        default_factory=lambda: {"RB": 0.5, "WR": 0.45, "TE": 0.05}
    )
    superflex_split: dict[str, float] = field(default_factory=lambda: {"QB": 1.0})
    position_sigma: dict[str, float] = field(
        default_factory=lambda: {"QB": 14, "RB": 10, "WR": 11, "TE": 9, "K": 20, "DEF": 20}
    )
    default_sigma: float = 12.0
    tie_epsilon: float = 0.02            # composite within 2% ⇒ FH flags break the tie
    top_n: int = 8
    run_window: int = 5
    run_threshold: int = 3
    run_boost_per_pick: float = 0.08
    need_fill_decay: float = 0.55        # multiplier per starter filled beyond need
    hard_cap_positions: tuple[str, ...] = ("K", "DEF")
    over_cap_penalty: float = 1000.0     # pushes over-rostered positions below any real option
    my_guy_tier_value: float = 8.0       # value points per tier of My-Guys boost
    cliff_boost: float = 0.2             # urgency bump when a player ends a tier at a cliff


@dataclass
class Recommendation:
    sleeper_id: str
    name: str
    position: str
    team: str | None
    composite_score: float
    base_vor: float
    tier: int | None
    survival_prob: float | None          # P(available at my next pick)
    flags: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


@dataclass
class RecommendationResult:
    recommendations: list[Recommendation]
    needs: dict[str, int]                # position -> starter slots still unfilled
    compute_ms: float = 0.0
