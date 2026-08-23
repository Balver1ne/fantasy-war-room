"""Parser tests on synthetic layout text — no real (subscriber) PDFs in fixtures."""

from warroom.ingest.pdf_extract import (
    _parse_list,
    _parse_rankings,
    _parse_sbb,
    detect_layout,
)

RANKINGS_TEXT = """FLEX RANKINGS (1-70)
# PLAYER POS TM BYE # PLAYER POS TM BYE
1 Bijan Robinson RB1 ATL 11 3 Jahmyr Gibbs RB2 DET 6
2 Ja'Marr Chase WR1 CIN 6 4 Puka Nacua WR2 LAR 11
QB RANKINGS
1 Josh Allen QB1 BUF 7
"""

VALUE_TEXT = """VALUE PICKS GUIDE
QB 3 PICKS WR 5 PICKS
JARED GOFF DET QB16 DJ MOORE BUF WR28
KYLER MURRAY MIN QB17 EMEKA EGBUKA TB WR22
"""

SBB_TEXT = """SLEEPERS 10 BREAKOUTS 9 BUSTS 6
QB KYLER MURRAY MIN JAKE QB CAM WARD TEN JAKE QB MALIK WILLIS MIA JAKE
RB BLAKE CORUM LAR KYLE RB EMEKA EGBUKA TB KYLE RB CHRISTIAN MCCAFFREY SF KYLE
"""


class TestDetectLayout:
    def test_layouts(self):
        assert detect_layout("TFH REDRAFT RANKINGS\nFLEX RANKINGS (1-70)") == "tfh_rankings"
        assert detect_layout("SLEEPERS BREAKOUTS BUSTS") == "tfh_sbb"
        assert detect_layout("TOP RB HANDCUFFS") == "tfh_handcuffs"
        assert detect_layout("VALUE PICKS GUIDE") == "tfh_value"
        assert detect_layout("something else") == "generic"


class TestRankings:
    def test_flex_only_stops_at_section_reset(self):
        headers, rows, mapping = _parse_rankings([RANKINGS_TEXT])
        # stops when rank "1" (Josh Allen, QB page) repeats — flex board only
        assert [r["name"] for r in rows] == [
            "Bijan Robinson", "Jahmyr Gibbs", "Ja'Marr Chase", "Puka Nacua"
        ]
        assert rows[0] == {"rank": "1", "name": "Bijan Robinson", "position": "RB1",
                           "team": "ATL", "bye": "11"}
        assert mapping["name"] == "name"


class TestValueList:
    def test_parse_and_flag_mapping(self):
        headers, rows, mapping = _parse_list([VALUE_TEXT], "value_pick")
        names = {r["name"] for r in rows}
        assert names == {"Jared Goff", "Dj Moore", "Kyler Murray", "Emeka Egbuka"}
        assert all(r["value_pick"] == "Y" for r in rows)
        assert mapping["value_pick"] == "flag:value_pick:bool"

    def test_section_header_noise_filtered(self):
        _, rows, _ = _parse_list([VALUE_TEXT], "value_pick")
        # "QB 3 PICKS" / "WR 5 PICKS" must not become rows
        assert all(" " in r["name"] and r["name"] not in ("Picks", "Qb") for r in rows)


class TestSbb:
    def test_three_columns_map_to_flags(self):
        headers, rows, mapping = _parse_sbb([SBB_TEXT])
        by_name = {r["name"]: r for r in rows}
        assert by_name["Kyler Murray"]["sleeper"] == "Y"
        assert by_name["Cam Ward"]["breakout"] == "Y"
        assert by_name["Malik Willis"]["bust"] == "Y"
        assert by_name["Christian Mccaffrey"]["bust"] == "Y"
        assert mapping["sleeper"] == "flag:sleeper:bool"
        # each row carries exactly one active flag
        for r in rows:
            assert [r["sleeper"], r["breakout"], r["bust"]].count("Y") == 1
