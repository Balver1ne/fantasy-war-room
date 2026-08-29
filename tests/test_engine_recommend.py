from engine_helpers import league_1qb, make_data
from warroom.engine.models import DraftState, EngineConfig, Preferences
from warroom.engine.recommend import recommend

CFG = EngineConfig()


def big_board(n=80):
    spec = []
    positions = ["RB", "WR", "RB", "WR", "TE", "QB"]
    for i in range(n):
        pos = positions[i % len(positions)]
        spec.append((str(i), f"P{i}", pos, i + 1))
    return spec


def test_drafted_and_dnd_excluded():
    data = make_data(big_board())
    ds = DraftState(drafted={"0", "1", "2"}, my_next_pick_no=15)
    prefs = Preferences(do_not_draft={"3"})
    res = recommend(ds, data, prefs, league_1qb())
    ids = {r.sleeper_id for r in res.recommendations}
    assert ids.isdisjoint({"0", "1", "2", "3"})


def test_my_guys_boost_lifts_player():
    data = make_data(big_board())
    ds = DraftState(my_next_pick_no=15)
    cfg = EngineConfig(top_n=80)  # full ordering so we can see the player move
    base = recommend(ds, data, Preferences(), league_1qb(), cfg)
    boosted = recommend(ds, data, Preferences(my_guys={"10": 3.0}), league_1qb(), cfg)
    base_ids = [r.sleeper_id for r in base.recommendations]
    boosted_ids = [r.sleeper_id for r in boosted.recommendations]
    # a My-Guys boost strictly improves the target's spot in the board
    assert boosted_ids.index("10") < base_ids.index("10")


def test_output_contract_fields_and_topn():
    data = make_data(big_board(), flags={"5": {"sleeper": True}}, flag_priority={"sleeper": 1},
                     adp={str(i): float(i + 1) for i in range(80)})
    ds = DraftState(my_roster=["0"], recent_positions=["RB", "RB", "RB"],
                    my_next_pick_no=15, my_next_pick_label="2.03")
    res = recommend(ds, data, Preferences(), league_1qb())
    assert len(res.recommendations) == CFG.top_n
    r = res.recommendations[0]
    assert r.name and r.position and r.composite_score is not None
    assert r.tier is not None
    assert all(len(x.reasons) <= 3 for x in res.recommendations)
    assert isinstance(res.needs, dict)


def test_recompute_under_200ms_full_board():
    # ~600 players, realistic universe slice; must be well under the 200ms budget
    spec = [(str(i), f"P{i}", ["RB", "WR", "TE", "QB"][i % 4], i + 1) for i in range(600)]
    data = make_data(spec, adp={str(i): float(i + 1) for i in range(600)})
    ds = DraftState(drafted={str(i) for i in range(50)}, my_next_pick_no=60)
    res = recommend(ds, data, Preferences(), league_1qb())
    assert res.compute_ms < 200.0
    assert res.recommendations


def test_board_value_ordered_keeps_filled_positions_with_vorp_vona():
    data = make_data(big_board())
    # I already hold 2 RB (indices 0 and 2 are RB in the big_board pattern)
    ds = DraftState(drafted={"0", "2"}, my_roster=["0", "2"], my_next_pick_no=15)
    res = recommend(ds, data, Preferences(), league_1qb())
    board = res.board

    # value-ordered, and every available player is present (never pruned by need)
    values = [b.value for b in board]
    assert values == sorted(values, reverse=True)
    assert len(board) == len(big_board()) - len(ds.drafted)

    # filling RB does not remove RBs from the board
    rbs = [b for b in board if b.position == "RB"]
    assert len(rbs) > 5

    # VORP present for all; VONA = drop-off to the next available RB is positive at the top
    assert all(b.vorp is not None for b in board)
    assert rbs[0].vona is not None and rbs[0].vona > 0


def test_no_available_players_returns_empty():
    data = make_data(big_board(5))
    ds = DraftState(drafted={"0", "1", "2", "3", "4"}, my_next_pick_no=15)
    res = recommend(ds, data, Preferences(), league_1qb())
    assert res.recommendations == []


def test_needs_summary_reflects_roster():
    data = make_data(big_board())
    # I hold 2 RB and 1 QB already
    ds = DraftState(my_roster=["0", "2", "5"], my_next_pick_no=15)
    # players 0,2 are RB, 5 is QB per big_board pattern
    res = recommend(ds, data, Preferences(), league_1qb())
    assert res.needs.get("RB", 0) == 0     # both RB starters filled
    assert res.needs.get("QB", 0) == 0     # QB filled
    assert res.needs.get("WR", 0) == 2     # WR still open
