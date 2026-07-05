import pytest
from warroom.names import normalize_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Marvin Harrison Jr.", "marvin harrison"),
        ("Kenneth Walker III", "kenneth walker"),
        ("D'Andre Swift", "dandre swift"),
        ("Amon-Ra St. Brown", "amonra st brown"),
        ("Michael Pittman Jr", "michael pittman"),
        ("Carolina Panthers", "carolina panthers"),
        ("  Christian   McCaffrey  ", "christian mccaffrey"),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected
