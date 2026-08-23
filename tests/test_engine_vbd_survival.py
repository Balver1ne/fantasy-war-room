from engine_helpers import league_1qb, league_superflex, make_data
from warroom.engine import consensus, survival, vbd
from warroom.engine.models import EngineConfig

CFG = EngineConfig()


def _qbs(n, rank_start=1):
    return [(f"qb{i}", f"QB{i}", "QB", rank_start + i) for i in range(n)]


def test_replacement_index_deeper_in_superflex():
    std = vbd.replacement_index("QB", league_1qb(), CFG)
    sfl = vbd.replacement_index("QB", league_superflex(), CFG)
    assert sfl > std  # superflex makes more QBs startable


def test_superflex_elevates_qb_value():
    # identical QB pool; QB VOR must be higher in superflex than 1QB
    spec = _qbs(30) + [(f"rb{i}", f"RB{i}", "RB", 40 + i) for i in range(30)]
    data = make_data(spec)
    blended = consensus.blend_values(data, CFG)

    base_std = vbd.replacement_values(blended, data, league_1qb(), CFG)
    base_sfl = vbd.replacement_values(blended, data, league_superflex(), CFG)
    vor_std = vbd.value_over_replacement(blended, data, base_std)
    vor_sfl = vbd.value_over_replacement(blended, data, base_sfl)

    assert vor_sfl["qb0"] > vor_std["qb0"]


def test_vor_positive_above_replacement_negative_below():
    spec = [(f"rb{i}", f"RB{i}", "RB", i + 1) for i in range(40)]
    data = make_data(spec)
    blended = consensus.blend_values(data, CFG)
    base = vbd.replacement_values(blended, data, league_1qb(), CFG)
    vor = vbd.value_over_replacement(blended, data, base)
    assert vor["rb0"] > 0        # elite RB well above replacement
    assert vor["rb39"] < 0       # deep RB below replacement


class TestSurvival:
    def test_bounds(self):
        assert survival.prob_available(None, 10, 12) is None
        p = survival.prob_available(20.0, 24, 10)
        assert 0.0 <= p <= 1.0

    def test_monotonic_in_pick(self):
        # later my pick ⇒ lower chance a given player survives
        early = survival.prob_available(20.0, 15, 10)
        late = survival.prob_available(20.0, 30, 10)
        assert early > late

    def test_monotonic_in_adp(self):
        # a player with later ADP is more likely to still be there
        p_early_adp = survival.prob_available(10.0, 24, 10)
        p_late_adp = survival.prob_available(40.0, 24, 10)
        assert p_late_adp > p_early_adp

    def test_at_adp_is_half(self):
        # when my pick equals ADP, ~50/50
        assert abs(survival.prob_available(24.0, 24, 10) - 0.5) < 1e-6

    def test_sigma_per_position(self):
        assert survival.sigma_for("RB", CFG) == CFG.position_sigma["RB"]
        assert survival.sigma_for("ZZ", CFG) == CFG.default_sigma
