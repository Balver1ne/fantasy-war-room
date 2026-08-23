"""Full-word position + team-alias normalization (Football Absurdity's 'Quarterback')."""

import pytest
from warroom.matching.normalize import canonical_position, canonical_team


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Quarterback", "QB"),
        ("Running Back", "RB"),
        ("Wide Receiver", "WR"),
        ("Tight End", "TE"),
        ("Kicker", "K"),
        ("Defense", "DEF"),
        ("RB1", "RB"),   # embedded rank still works
        ("QB16", "QB"),
        ("D/ST", "DEF"),
    ],
)
def test_full_word_and_coded_positions(raw, expected):
    assert canonical_position(raw) == expected


def test_arizona_alias():
    assert canonical_team("AZ") == "ARI"
    assert canonical_team("ARZ") == "ARI"
