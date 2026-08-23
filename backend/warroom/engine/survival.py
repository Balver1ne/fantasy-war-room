"""5.3 Survival probability: P(player still available at my next pick).

Model ADP as roughly normal with a position-dependent spread. A player is available at
pick p if his realized draft slot lands at or after p, so P(available) = P(slot ≥ p) =
1 − Φ((p − adp) / σ). Earlier ADP than my pick ⇒ low chance he's back.
"""

import math

from warroom.engine.models import EngineConfig


def _phi(x: float) -> float:
    """Standard normal CDF via the error function (stdlib, no scipy)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def prob_available(
    adp: float | None, pick_no: int | None, sigma: float
) -> float | None:
    if adp is None or pick_no is None or sigma <= 0:
        return None
    prob = 1.0 - _phi((pick_no - adp) / sigma)
    return max(0.0, min(1.0, prob))


def sigma_for(position: str, config: EngineConfig) -> float:
    return config.position_sigma.get(position, config.default_sigma)
