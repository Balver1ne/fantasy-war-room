"""Integration replay (DESIGN.md §9): drive a full snake mock draft through the engine,
asserting recommendations never include a drafted player and every recompute is <200ms."""

from engine_helpers import league_1qb, make_data
from warroom.engine.models import DraftState, Preferences
from warroom.engine.recommend import recommend

TEAMS = 12
ROUNDS = 8


def _board(n=140):
    spec = [
        (str(i), f"P{i}", ["RB", "WR", "TE", "QB", "RB", "WR"][i % 6], i + 1)
        for i in range(n)
    ]
    return make_data(spec, adp={str(i): float(i + 1) for i in range(n)})


def test_replay_never_recommends_drafted_and_is_fast():
    data = _board()
    league = league_1qb()
    rosters: dict[int, list[str]] = {t: [] for t in range(TEAMS)}
    drafted: set[str] = set()
    recent: list[str] = []
    max_ms = 0.0
    picks = 0

    order = list(range(TEAMS))
    for rnd in range(ROUNDS):
        seq = order if rnd % 2 == 0 else list(reversed(order))
        for team in seq:
            ds = DraftState(
                drafted=set(drafted),
                my_roster=list(rosters[team]),
                recent_positions=list(recent),
                current_pick_no=picks + 1,
                my_next_pick_no=picks + 1 + TEAMS,
            )
            res = recommend(ds, data, Preferences(), league)
            max_ms = max(max_ms, res.compute_ms)

            assert res.recommendations, "engine must always surface a pick"
            # the core invariant: nothing already drafted is ever recommended
            assert all(r.sleeper_id not in drafted for r in res.recommendations)

            taken = res.recommendations[0]
            drafted.add(taken.sleeper_id)
            rosters[team].append(taken.sleeper_id)
            recent.append(taken.position)
            picks += 1

    assert picks == TEAMS * ROUNDS
    assert max_ms < 200.0
    # the over-cap penalty must keep the engine from ever stockpiling QBs in a 1QB league
    for team in range(TEAMS):
        qbs = sum(1 for sid in rosters[team] if data.players[sid].position == "QB")
        assert qbs <= 2


def test_replay_respects_do_not_draft_throughout():
    data = _board()
    dnd = {"0", "1", "2"}
    drafted: set[str] = set()
    for _ in range(20):
        ds = DraftState(drafted=set(drafted), my_next_pick_no=len(drafted) + 13)
        res = recommend(ds, data, Preferences(do_not_draft=dnd), league_1qb())
        assert all(r.sleeper_id not in dnd for r in res.recommendations)
        drafted.add(res.recommendations[0].sleeper_id)
    assert dnd.isdisjoint(drafted)
