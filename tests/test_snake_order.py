import pytest
from warroom.sync.snake import (
    DraftOrderConfig,
    format_pick,
    next_pick_no_for,
    owner_of_pick,
    picks_until,
    slot_for_pick,
)


def cfg(
    team_count: int = 12,
    rounds: int = 15,
    draft_type: str = "snake",
    reversal_round: int = 0,
    slot_to_roster: dict[int, int | None] | None = None,
    traded: dict[tuple[int, int], int] | None = None,
) -> DraftOrderConfig:
    return DraftOrderConfig(
        team_count=team_count,
        rounds=rounds,
        draft_type=draft_type,
        reversal_round=reversal_round,
        slot_to_roster=slot_to_roster or {},
        traded=traded or {},
    )


def slots_in_round(c: DraftOrderConfig, round_no: int) -> list[int]:
    start = (round_no - 1) * c.team_count + 1
    return [slot_for_pick(no, c)[1] for no in range(start, start + c.team_count)]


IDENTITY_12 = {slot: slot for slot in range(1, 13)}


class TestPlainSnake:
    def test_round_sequences(self):
        c = cfg()
        asc = list(range(1, 13))
        desc = list(range(12, 0, -1))
        assert slots_in_round(c, 1) == asc
        assert slots_in_round(c, 2) == desc
        assert slots_in_round(c, 3) == asc
        assert slots_in_round(c, 4) == desc

    def test_round_boundaries(self):
        c = cfg()
        assert slot_for_pick(12, c) == (1, 12)
        assert slot_for_pick(13, c) == (2, 12)
        assert slot_for_pick(24, c) == (2, 1)
        assert slot_for_pick(25, c) == (3, 1)

    @pytest.mark.parametrize("team_count", [8, 10, 12, 14])
    def test_turn_pick_stays_on_last_slot(self, team_count):
        c = cfg(team_count=team_count)
        assert slot_for_pick(team_count, c) == (1, team_count)
        assert slot_for_pick(team_count + 1, c) == (2, team_count)


class TestThirdRoundReversal:
    def test_round_sequences(self):
        c = cfg(reversal_round=3)
        asc = list(range(1, 13))
        desc = list(range(12, 0, -1))
        assert slots_in_round(c, 1) == asc
        assert slots_in_round(c, 2) == desc
        assert slots_in_round(c, 3) == desc  # the reversal: two descending rounds in a row
        assert slots_in_round(c, 4) == asc
        assert slots_in_round(c, 5) == desc

    def test_round_boundaries(self):
        c = cfg(reversal_round=3)
        assert slot_for_pick(24, c) == (2, 1)
        assert slot_for_pick(25, c) == (3, 12)
        assert slot_for_pick(36, c) == (3, 1)
        assert slot_for_pick(37, c) == (4, 1)


class TestLinear:
    def test_every_round_ascends(self):
        c = cfg(draft_type="linear")
        for round_no in range(1, 6):
            assert slots_in_round(c, round_no) == list(range(1, 13))


class TestTradedPicks:
    # Roster 4 traded its round-2 pick to roster 9; roster 4 acquired roster 1's round-3 pick.
    TRADED = {(2, 4): 9, (3, 1): 4}

    def c(self) -> DraftOrderConfig:
        return cfg(slot_to_roster=IDENTITY_12, traded=self.TRADED)

    def test_owner_remap(self):
        c = self.c()
        # Round 2 descends: slot 4 is pick 21.
        assert slot_for_pick(21, c) == (2, 4)
        assert owner_of_pick(21, c) == 9
        # Untraded picks keep their original owner.
        assert owner_of_pick(24, c) == 1  # round 2, slot 1
        # Round 3 ascends: slot 1 is pick 25 — original roster 1, traded to 4.
        assert owner_of_pick(25, c) == 4

    def test_traded_away_skips_to_next_retained_pick(self):
        c = self.c()
        # After pick 12, roster 4's round-2 pick is gone; its next is the acquired pick 25.
        assert next_pick_no_for(12, c, roster_id=4) == 25
        assert picks_until(12, c, roster_id=4) == 12

    def test_acquirer_gets_earliest_of_its_picks(self):
        c = self.c()
        # Roster 9's own round-2 pick (slot 9, descending) is pick 16 — before the acquired 21.
        assert next_pick_no_for(12, c, roster_id=9) == 16

    def test_no_trades_identity(self):
        c = cfg(slot_to_roster=IDENTITY_12)
        assert owner_of_pick(21, c) == 4
        assert next_pick_no_for(12, c, roster_id=4) == 21


class TestMockDraftMode:
    def test_owner_unknown_identify_by_slot(self):
        c = cfg()  # empty slot_to_roster, as in Sleeper mocks
        assert owner_of_pick(1, c) is None
        assert next_pick_no_for(0, c, slot=4) == 4
        assert picks_until(0, c, slot=4) == 3
        # Snake wraparound: after my pick 4, next is round 2 slot 4 = pick 21.
        assert next_pick_no_for(4, c, slot=4) == 21

    def test_no_identity_given(self):
        c = cfg()
        assert next_pick_no_for(0, c) is None
        assert picks_until(0, c) is None


class TestEdges:
    def test_beyond_draft_end(self):
        c = cfg(rounds=2)
        assert next_pick_no_for(24, c, slot=4) is None
        assert picks_until(24, c, slot=1) is None

    def test_last_pick_of_draft(self):
        c = cfg(rounds=2)
        # Round 2 descends: slot 1 owns the final pick (24).
        assert next_pick_no_for(23, c, slot=1) == 24

    def test_format_pick(self):
        c = cfg()
        assert format_pick(1, c) == "1.01"
        assert format_pick(15, c) == "2.03"
        assert format_pick(25, c) == "3.01"
