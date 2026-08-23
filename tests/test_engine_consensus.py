from engine_helpers import make_data
from warroom.engine import consensus
from warroom.engine.models import EngineConfig

CFG = EngineConfig()


def test_value_curve_monotonic_and_top_heavy():
    v = consensus.value_from_rank
    hl = CFG.value_half_life
    assert v(1, hl) == 100.0
    # strictly decreasing
    assert v(1, hl) > v(5, hl) > v(50, hl) > v(150, hl)
    # top-end gaps are larger than deep gaps (the whole point of a value curve)
    assert (v(1, hl) - v(6, hl)) > (v(100, hl) - v(105, hl))


def test_blend_is_weighted_average_of_values():
    # two sources disagree on player B; weight source1 heavier
    data = make_data(
        [("a", "A", "RB", 1), ("b", "B", "RB", 1)],
        sources={"s1": {"a": 1, "b": 10}, "s2": {"a": 1, "b": 30}},
        weights={"s1": 3.0, "s2": 1.0},
    )
    blended = consensus.blend_values(data, CFG)
    v = consensus.value_from_rank
    expected_b = (3 * v(10, CFG.value_half_life) + 1 * v(30, CFG.value_half_life)) / 4
    assert abs(blended["b"] - expected_b) < 1e-9
    assert blended["a"] == 100.0


def test_missing_source_does_not_penalize():
    data = make_data(
        [("a", "A", "RB", 1), ("b", "B", "RB", 5)],
        sources={"s1": {"a": 1, "b": 5}, "s2": {"a": 1}},  # s2 omits b
    )
    blended = consensus.blend_values(data, CFG)
    # b's value is just s1's value, not diluted by a zero from s2
    assert abs(blended["b"] - consensus.value_from_rank(5, CFG.value_half_life)) < 1e-9


def test_tiers_from_gap_detection():
    # ranks 1,2 close; big jump to 20,21; another to 60
    spec = [("a", "A", "WR", 1), ("b", "B", "WR", 2),
            ("c", "C", "WR", 20), ("d", "D", "WR", 21),
            ("e", "E", "WR", 60)]
    data = make_data(spec)
    blended = consensus.blend_values(data, CFG)
    tiers = consensus.position_tiers(blended, data, CFG)
    assert tiers["a"] == tiers["b"] == 1
    assert tiers["c"] == tiers["d"] == 2
    assert tiers["e"] == 3


def test_tier_override_applied():
    data = make_data([("a", "A", "RB", 1), ("b", "B", "RB", 2)])
    blended = consensus.blend_values(data, CFG)
    tiers = consensus.position_tiers(blended, data, CFG, tier_overrides={"b": 5})
    assert tiers["b"] == 5


def test_tier_value_drop_measures_next_tier_cliff():
    spec = [("a", "A", "RB", 1), ("b", "B", "RB", 2), ("c", "C", "RB", 40)]
    data = make_data(spec)
    blended = consensus.blend_values(data, CFG)
    tiers = consensus.position_tiers(blended, data, CFG)
    avail = {"a", "b", "c"}
    drop = consensus.tier_value_drop("b", avail, blended, tiers, data)
    assert drop is not None and drop > CFG.tier_gap_threshold
    # last player has no next tier
    assert consensus.tier_value_drop("c", avail, blended, tiers, data) is None
