"""Team and position normalization — the "known landmines" from DESIGN.md §3.

Different ranking sources spell team abbreviations and positions inconsistently
(JAX/JAC, WAS/WSH, LA/LAR, D/ST vs DEF vs DST). Everything is canonicalized to the
Sleeper convention before matching.
"""

import re

# Variant -> Sleeper-canonical team abbreviation.
_TEAM_ALIASES = {
    "JAC": "JAX",
    "WSH": "WAS",
    "LA": "LAR",
    "STL": "LAR",
    "SD": "LAC",
    "OAK": "LV",
    "LVR": "LV",
    "ARZ": "ARI",
    "GBP": "GB",
    "KCC": "KC",
    "NEP": "NE",
    "NOS": "NO",
    "SFO": "SF",
    "TBB": "TB",
    "NNE": "NE",
}

_DEF_TOKENS = {"DEF", "DST", "D/ST", "DS", "D"}
_POS_CANON = {"QB", "RB", "WR", "TE", "K", "PK", "DEF"}


def canonical_team(team: str | None) -> str | None:
    if not team:
        return None
    t = team.strip().upper()
    return _TEAM_ALIASES.get(t, t) or None


def canonical_position(position: str | None) -> str | None:
    """Normalize a position token, stripping any embedded positional rank.

    FantasyPros encodes rank in the position, e.g. "RB1" -> RB. D/ST spellings all
    collapse to DEF; kicker PK -> K.
    """
    if not position:
        return None
    p = position.strip().upper()
    p = re.sub(r"\s+", "", p)
    if p in _DEF_TOKENS or p.startswith("D/ST") or p.startswith("DST"):
        return "DEF"
    # strip trailing digits (RB1 -> RB, WR12 -> WR)
    letters = re.sub(r"\d+$", "", p)
    if letters == "PK":
        return "K"
    return letters if letters in _POS_CANON else (letters or None)


def position_rank_from(position: str | None) -> int | None:
    """Extract the positional rank baked into a token like "RB1" -> 1."""
    if not position:
        return None
    m = re.search(r"(\d+)$", position.strip())
    return int(m.group(1)) if m else None
