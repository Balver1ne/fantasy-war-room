from engine_helpers import league_1qb, league_superflex, make_data
from warroom.engine import adjustments, tiebreak
from warroom.engine.models import EngineConfig

CFG = EngineConfig()


class TestRosterNeed:
    def test_full_need_when_slot_empty(self):
        assert adjustments.roster_need_multiplier("RB", 0, league_1qb(), CFG) == 1.0

    def test_diminishing_returns_past_need(self):
        m2 = adjustments.roster_need_multiplier("RB", 2, league_1qb(), CFG)
        m3 = adjustments.roster_need_multiplier("RB", 3, league_1qb(), CFG)
        assert 0 < m3 < m2 <= 1.0

    def test_hard_cap_no_fourth_qb_in_1qb(self):
        # 1QB league: a 3rd/4th QB is near-worthless
        m = adjustments.roster_need_multiplier("QB", 3, league_1qb(), CFG)
        assert m <= 0.05

    def test_superflex_keeps_qb_need_up(self):
        # with superflex, a 2nd QB is still wanted (multiplier not crushed)
        m = adjustments.roster_need_multiplier("QB", 1, league_superflex(), CFG)
        assert m == 1.0

    def test_kicker_defense_suppressed_once_filled(self):
        assert adjustments.roster_need_multiplier("K", 1, league_1qb(), CFG) <= 0.05
        assert adjustments.roster_need_multiplier("DEF", 1, league_1qb(), CFG) <= 0.05


class TestRunBoost:
    def test_boost_when_run_detected(self):
        recent = ["WR", "RB", "RB", "RB", "WR"]  # 3 RB in last 5
        assert adjustments.run_boost("RB", recent, CFG) > 0
        assert adjustments.run_boost("TE", recent, CFG) == 0.0

    def test_no_boost_below_threshold(self):
        recent = ["RB", "WR", "TE", "QB", "WR"]  # 2 WR only
        assert adjustments.run_boost("WR", recent, CFG) == 0.0


class TestTiebreak:
    def _data(self):
        return make_data(
            [("a", "Alpha", "RB", 1), ("b", "Bravo", "RB", 1), ("c", "Cee", "RB", 1)],
            flags={"a": {"rz": True}, "b": {"rz": False}},
            flag_priority={"rz": 10},
        )

    def test_flag_breaks_near_tie(self):
        data = self._data()
        scored = [
            tiebreak.Scored("a", 100.0, 0.5),
            tiebreak.Scored("b", 100.5, 0.5),  # b slightly higher but within epsilon
        ]
        order = tiebreak.order_with_tiebreaks(scored, data, CFG)
        assert order[0] == "a"  # red-zone flag wins the tie

    def test_clear_gap_not_overridden_by_flag(self):
        data = self._data()
        scored = [
            tiebreak.Scored("b", 200.0, 0.5),  # far ahead
            tiebreak.Scored("a", 100.0, 0.5),
        ]
        order = tiebreak.order_with_tiebreaks(scored, data, CFG)
        assert order[0] == "b"  # not a tie → flag irrelevant

    def test_survival_fallback_when_no_flag_edge(self):
        data = make_data([("a", "A", "RB", 1), ("b", "B", "RB", 1)])  # no flags
        scored = [
            tiebreak.Scored("a", 100.0, 0.8),   # likely to survive
            tiebreak.Scored("b", 100.0, 0.2),   # take him or lose him
        ]
        order = tiebreak.order_with_tiebreaks(scored, data, CFG)
        assert order[0] == "b"  # lower survival first

    def test_flag_priority_ordering(self):
        data = make_data(
            [("a", "A", "RB", 1), ("b", "B", "RB", 1)],
            flags={"a": {"low": True}, "b": {"high": True}},
            flag_priority={"high": 20, "low": 5},
        )
        scored = [tiebreak.Scored("a", 100.0, 0.5), tiebreak.Scored("b", 100.0, 0.5)]
        order = tiebreak.order_with_tiebreaks(scored, data, CFG)
        assert order[0] == "b"  # higher-priority flag wins
