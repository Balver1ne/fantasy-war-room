from pathlib import Path

import pytest
from sqlalchemy import select
from warroom.db import repo
from warroom.db.models import (
    FlagType,
    Player,
    PlayerAlias,
    PlayerFlag,
    Ranking,
    RankingSet,
)
from warroom.ingest import service
from warroom.ingest.csv_parse import parse_csv
from warroom.ingest.mapping import auto_map, parse_flag, validate_mapping
from warroom.names import normalize_name

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "ingest"

UNIVERSE = [
    ("1001", "Christian McCaffrey", "RB", "SF"),
    ("1002", "Justin Jefferson", "WR", "MIN"),
    ("1005", "Bijan Robinson", "RB", "ATL"),
    ("1003", "Marvin Harrison Jr.", "WR", "ARI"),
    ("1010", "Amon-Ra St. Brown", "WR", "DET"),
]


@pytest.fixture
def db(session_factory):
    with session_factory() as s:
        for sid, name, pos, team in UNIVERSE:
            s.add(
                Player(
                    sleeper_id=sid,
                    name=name,
                    name_normalized=normalize_name(name),
                    position=pos,
                    team=team,
                )
            )
        s.commit()
    return session_factory


def load_csv():
    text = (FIXTURES / "fantasypros_sample.csv").read_text()
    return parse_csv(text)


class TestParseAndMap:
    def test_parse_headers_and_rows(self):
        headers, rows = load_csv()
        assert headers[:5] == ["RK", "TIERS", "PLAYER NAME", "TEAM", "POS"]
        assert len(rows) == 6
        assert rows[0]["PLAYER NAME"] == "Christian McCaffrey"

    def test_auto_map_fantasypros(self):
        headers, _ = load_csv()
        m = auto_map(headers)
        assert m["PLAYER NAME"] == "name"
        assert m["TEAM"] == "team"
        assert m["POS"] == "position"
        assert m["RK"] == "rank"
        assert m["TIERS"] == "tier"

    def test_validate_requires_name(self):
        assert validate_mapping({"X": "rank"}) == ["A column must be mapped to 'name'."]
        assert validate_mapping({"PLAYER NAME": "name"}) == []

    def test_parse_flag_spec(self):
        assert parse_flag("flag:rb_confidence:numeric") == ("rb_confidence", "numeric")
        assert parse_flag("flag:red_zone") == ("red_zone", "numeric")
        assert parse_flag("flag:has_it:bool") == ("has_it", "bool")
        assert parse_flag("rank") is None


class TestImportFlow:
    def _job(self, s):
        headers, rows = load_csv()
        job = service.create_job(
            s,
            source="FantasyPros",
            headers=headers,
            rows=rows,
            scoring_format="half_ppr",
            source_filename="fantasypros_sample.csv",
        )
        mapping = job.mappings
        mapping["RB_CONFIDENCE"] = "flag:rb_confidence:numeric"
        service.set_mapping(s, job, mapping)
        return job

    def test_matches_all_but_unknown(self, db):
        with db() as s:
            job = self._job(s)
            summary = service.run_matching(s, job)
            assert summary["total"] == 6
            assert summary["matched"] == 5
            assert summary["unmatched"] == 1
            outstanding = service.unresolved_rows(job)
            assert len(outstanding) == 1
            assert outstanding[0]["name"] == "Totally Unknown Rookie"

    def test_commit_blocked_until_resolved(self, db):
        with db() as s:
            job = self._job(s)
            service.run_matching(s, job)
            with pytest.raises(service.IngestError, match="unresolved"):
                service.commit(s, job)

    def test_resolve_skip_then_commit_creates_set(self, db):
        with db() as s:
            job = self._job(s)
            service.run_matching(s, job)
            # skip the unknown rookie, then commit
            service.skip_row(s, job, 5)
            rset = service.commit(s, job, label="FP week 1")
            s.commit()
            rid = rset.id

        with db() as s:
            rset = s.get(RankingSet, rid)
            assert rset.scoring_format == "half_ppr"
            assert rset.active is True
            assert rset.row_count == 5
            rankings = s.scalars(
                select(Ranking).where(Ranking.ranking_set_id == rid)
            ).all()
            assert len(rankings) == 5
            cmc = next(r for r in rankings if r.sleeper_id == "1001")
            assert cmc.rank == 1 and cmc.tier == 1
            assert cmc.position_rank == 1  # derived from "RB1"
            # flags landed
            flags = s.scalars(select(PlayerFlag)).all()
            assert len(flags) == 5
            assert s.get(FlagType, "rb_confidence").value_kind == "numeric"
            cmc_flag = next(f for f in flags if f.sleeper_id == "1001")
            assert cmc_flag.value_num == 5.0

    def test_manual_resolve_learns_alias(self, db):
        with db() as s:
            job = self._job(s)
            service.run_matching(s, job)
            # resolve the unknown rookie to CMC (contrived) and confirm alias persists
            service.resolve_row(s, job, 5, "1001")
            s.commit()
        with db() as s:
            aliases = s.scalars(select(PlayerAlias)).all()
            assert any(a.alias_normalized == normalize_name("Totally Unknown Rookie")
                       and a.sleeper_id == "1001" for a in aliases)
            # and repo.load_aliases exposes it for the next import
            assert repo.load_aliases(s)[normalize_name("Totally Unknown Rookie")] == "1001"

    def test_reimport_deactivates_prior_set(self, db):
        with db() as s:
            job = self._job(s)
            service.run_matching(s, job)
            service.skip_row(s, job, 5)
            first = service.commit(s, job)
            s.commit()
            first_id = first.id
        with db() as s:
            job2 = self._job(s)
            service.run_matching(s, job2)
            service.skip_row(s, job2, 5)
            service.commit(s, job2)
            s.commit()
        with db() as s:
            first = s.get(RankingSet, first_id)
            assert first.active is False
            active = s.scalars(select(RankingSet).where(RankingSet.active.is_(True))).all()
            assert len(active) == 1
