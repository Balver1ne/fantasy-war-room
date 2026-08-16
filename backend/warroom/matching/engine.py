"""Player matching: ranking-source rows → canonical Sleeper player_id.

Strategy (DESIGN.md §3), highest confidence first:
  1. alias table (manual + learned resolutions) — never re-ask a resolved name
  2. exact normalized name + position (unique)
  3. exact normalized name + team (unique)
  4. fuzzy name (rapidfuzz, threshold ~90) constrained by position/team (unique best)
  5. otherwise → UNMATCHED, carrying top candidates for the resolution UI

Name collisions (two players sharing a normalized name+position) never auto-resolve;
they go to the queue with both candidates. A silent wrong match is worse than useless.
"""

from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from warroom.matching.normalize import canonical_position, canonical_team
from warroom.names import normalize_name

FUZZY_THRESHOLD = 90


@dataclass(frozen=True)
class PlayerRef:
    sleeper_id: str
    name: str
    name_normalized: str
    position: str | None
    team: str | None


@dataclass(frozen=True)
class Candidate:
    sleeper_id: str
    name: str
    position: str | None
    team: str | None
    score: float  # 0-100


@dataclass
class MatchResult:
    sleeper_id: str | None
    method: str  # alias | exact_pos | exact_team | fuzzy | unmatched | ambiguous
    score: float
    candidates: list[Candidate] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return self.sleeper_id is not None


class MatchIndex:
    """Prebuilt lookup over the player universe. Build once per import, not per row."""

    def __init__(self, players: list[PlayerRef], aliases: dict[str, str] | None = None):
        self.players = players
        self.by_id = {p.sleeper_id: p for p in players}
        self.aliases = aliases or {}  # alias_normalized -> sleeper_id
        self._by_name_pos: dict[tuple[str, str], list[PlayerRef]] = {}
        self._by_name_team: dict[tuple[str, str], list[PlayerRef]] = {}
        self._by_name: dict[str, list[PlayerRef]] = {}
        self._def_by_team: dict[str, PlayerRef] = {}
        for p in players:
            self._by_name.setdefault(p.name_normalized, []).append(p)
            if p.position:
                self._by_name_pos.setdefault((p.name_normalized, p.position), []).append(p)
            if p.team:
                self._by_name_team.setdefault((p.name_normalized, p.team), []).append(p)
            if p.position == "DEF" and p.team:
                self._def_by_team[p.team] = p
        # rapidfuzz works fastest against a flat list of choices
        self._choice_names = [p.name_normalized for p in players]

    def _candidates(self, refs: list[PlayerRef], score: float) -> list[Candidate]:
        return [Candidate(p.sleeper_id, p.name, p.position, p.team, score) for p in refs]

    def match(self, name: str, position: str | None = None, team: str | None = None) -> MatchResult:
        norm = normalize_name(name)
        pos = canonical_position(position)
        tm = canonical_team(team)

        # 1. alias (manual/learned) — trust it outright
        if norm in self.aliases:
            sid = self.aliases[norm]
            ref = self.by_id.get(sid)
            return MatchResult(sid, "alias", 100.0, self._candidates([ref], 100.0) if ref else [])

        # DEF is identified by team, not name (Sleeper DEF id == team abbr)
        if pos == "DEF" and tm and tm in self._def_by_team:
            ref = self._def_by_team[tm]
            return MatchResult(ref.sleeper_id, "exact_team", 100.0, self._candidates([ref], 100.0))

        # 2. exact name + position
        if pos:
            hits = self._by_name_pos.get((norm, pos), [])
            if len(hits) == 1:
                return MatchResult(hits[0].sleeper_id, "exact_pos", 100.0, self._candidates(hits, 100.0))
            if len(hits) > 1:
                # narrow the collision by team if we have one
                if tm:
                    narrowed = [h for h in hits if h.team == tm]
                    if len(narrowed) == 1:
                        return MatchResult(
                            narrowed[0].sleeper_id, "exact_team", 100.0,
                            self._candidates(narrowed, 100.0),
                        )
                return MatchResult(None, "ambiguous", 100.0, self._candidates(hits, 100.0))

        # 3. exact name + team
        if tm:
            hits = self._by_name_team.get((norm, tm), [])
            if len(hits) == 1:
                return MatchResult(hits[0].sleeper_id, "exact_team", 100.0, self._candidates(hits, 100.0))
            if len(hits) > 1:
                return MatchResult(None, "ambiguous", 100.0, self._candidates(hits, 100.0))

        # exact name alone, unique
        name_hits = self._by_name.get(norm, [])
        if len(name_hits) == 1 and not pos and not tm:
            return MatchResult(name_hits[0].sleeper_id, "exact_pos", 100.0,
                               self._candidates(name_hits, 100.0))

        # 4. fuzzy, constrained by position/team when available
        return self._fuzzy(norm, pos, tm)

    def _fuzzy(self, norm: str, pos: str | None, tm: str | None) -> MatchResult:
        raw = process.extract(norm, self._choice_names, scorer=fuzz.WRatio, limit=10)
        seen: set[str] = set()
        cands: list[Candidate] = []
        for _matched_name, score, idx in raw:
            ref = self.players[idx]
            if ref.sleeper_id in seen:
                continue
            seen.add(ref.sleeper_id)
            if pos and ref.position and ref.position != pos:
                continue
            if tm and ref.team and ref.team != tm and score < 97:
                continue
            cands.append(Candidate(ref.sleeper_id, ref.name, ref.position, ref.team, float(score)))

        strong = [c for c in cands if c.score >= FUZZY_THRESHOLD]
        if len(strong) == 1:
            return MatchResult(strong[0].sleeper_id, "fuzzy", strong[0].score, cands[:5])
        if len(strong) > 1 and strong[0].score - strong[1].score >= 5:
            # a clear winner over the runner-up
            return MatchResult(strong[0].sleeper_id, "fuzzy", strong[0].score, cands[:5])
        return MatchResult(None, "unmatched", strong[0].score if strong else 0.0, cands[:5])
