import pytest
from warroom.matching.engine import MatchIndex, PlayerRef
from warroom.matching.normalize import (
    canonical_position,
    canonical_team,
    position_rank_from,
)
from warroom.names import normalize_name


def ref(sid, name, pos, team) -> PlayerRef:
    return PlayerRef(sid, name, normalize_name(name), pos, team)


UNIVERSE = [
    ref("1001", "Christian McCaffrey", "RB", "SF"),
    ref("1002", "Justin Jefferson", "WR", "MIN"),
    ref("1003", "Marvin Harrison Jr.", "WR", "ARI"),
    ref("1005", "Bijan Robinson", "RB", "ATL"),
    ref("1010", "Amon-Ra St. Brown", "WR", "DET"),
    ref("1011", "D'Andre Swift", "RB", "CHI"),
    ref("1012", "Kenneth Walker III", "RB", "SEA"),
    # name collision: two Mike Williams / Michael Thomas style
    ref("2001", "Michael Pittman", "WR", "IND"),
    ref("2002", "Michael Thomas", "WR", "NO"),
    ref("3001", "Mike Williams", "WR", "LAC"),
    ref("3002", "Mike Williams", "WR", "PIT"),  # deliberate collision
    # D/ST — Sleeper id is the team abbr
    ref("JAX", "Jacksonville Jaguars", "DEF", "JAX"),
    ref("WAS", "Washington Commanders", "DEF", "WAS"),
]


@pytest.fixture
def index() -> MatchIndex:
    return MatchIndex(UNIVERSE)


class TestNormalize:
    def test_position_strips_embedded_rank(self):
        assert canonical_position("RB1") == "RB"
        assert canonical_position("WR12") == "WR"
        assert position_rank_from("RB1") == 1
        assert position_rank_from("WR12") == 12

    def test_position_dst_variants(self):
        for token in ["DST", "DEF", "D/ST", "D"]:
            assert canonical_position(token) == "DEF"

    def test_kicker_alias(self):
        assert canonical_position("PK") == "K"

    def test_team_aliases(self):
        assert canonical_team("JAC") == "JAX"
        assert canonical_team("WSH") == "WAS"
        assert canonical_team("LA") == "LAR"
        assert canonical_team("OAK") == "LV"
        assert canonical_team("SF") == "SF"


class TestExactMatch:
    def test_exact_name_position(self, index):
        r = index.match("Christian McCaffrey", "RB", "SF")
        assert r.matched and r.sleeper_id == "1001" and r.method == "exact_pos"

    def test_fantasypros_pos_with_rank(self, index):
        # "RB2" must normalize to RB before matching
        r = index.match("Bijan Robinson", "RB2", "ATL")
        assert r.sleeper_id == "1005"

    def test_suffix_and_punctuation(self, index):
        assert index.match("Marvin Harrison", "WR", "ARI").sleeper_id == "1003"
        assert index.match("DAndre Swift", "RB", "CHI").sleeper_id == "1011"
        assert index.match("Kenneth Walker", "RB", "SEA").sleeper_id == "1012"
        assert index.match("Amon-Ra St Brown", "WR", "DET").sleeper_id == "1010"

    def test_team_alias_in_match(self, index):
        # source says JAC, Sleeper says JAX
        assert index.match("Jacksonville Jaguars", "DST", "JAC").sleeper_id == "JAX"
        assert index.match("Washington", "DEF", "WSH").sleeper_id == "WAS"


class TestCollisions:
    def test_name_collision_unresolved_by_name_alone(self, index):
        r = index.match("Mike Williams", "WR", None)
        assert not r.matched
        assert r.method == "ambiguous"
        assert {c.sleeper_id for c in r.candidates} == {"3001", "3002"}

    def test_collision_resolved_by_team(self, index):
        r = index.match("Mike Williams", "WR", "PIT")
        assert r.matched and r.sleeper_id == "3002" and r.method == "exact_team"

    def test_different_players_same_first_name_not_confused(self, index):
        assert index.match("Michael Pittman", "WR", "IND").sleeper_id == "2001"
        assert index.match("Michael Thomas", "WR", "NO").sleeper_id == "2002"


class TestFuzzy:
    def test_minor_typo_resolves(self, index):
        r = index.match("Bijan Robnson", "RB", "ATL")  # missing 'i'
        assert r.matched and r.sleeper_id == "1005" and r.method == "fuzzy"

    def test_nickname_far_off_goes_to_queue(self, index):
        r = index.match("Zxqwv Nobody", "WR", None)
        assert not r.matched
        assert r.method == "unmatched"


class TestAlias:
    def test_alias_short_circuits(self):
        idx = MatchIndex(UNIVERSE, aliases={normalize_name("Hollywood Brown"): "1002"})
        r = idx.match("Hollywood Brown", "WR", "MIN")
        assert r.matched and r.sleeper_id == "1002" and r.method == "alias"
