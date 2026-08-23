"""Shared builders for engine tests."""

from warroom.engine.models import LeagueSettings, PlayerMeta, RankingData, RankRow


def make_data(players_spec, *, source="FP", adp=None, flags=None, flag_priority=None,
              weights=None, sources=None):
    """players_spec: list of (sid, name, position, rank). Single-source unless `sources`
    (dict of source -> {sid: rank}) is given."""
    players = {sid: PlayerMeta(sid, name, pos) for sid, name, pos, _ in players_spec}
    if sources is None:
        rows = {sid: RankRow(rank=rank) for sid, _, _, rank in players_spec}
        sources = {source: rows}
        weights = weights or {source: 1.0}
    else:
        sources = {
            s: {sid: RankRow(rank=r) for sid, r in rows.items()}
            for s, rows in sources.items()
        }
        weights = weights or {s: 1.0 for s in sources}
    return RankingData(
        players=players, sources=sources, weights=weights,
        adp=adp or {}, flags=flags or {}, flag_priority=flag_priority or {},
    )


def league_1qb(team_count=12):
    return LeagueSettings(
        team_count=team_count,
        starters={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "K": 1, "DEF": 1}, flex=1,
    )


def league_superflex(team_count=12):
    return LeagueSettings(
        team_count=team_count,
        starters={"QB": 1, "RB": 2, "WR": 2, "TE": 1}, flex=1, superflex=1,
    )
