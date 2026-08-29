"""Column-mapping wizard support: the target fields and a heuristic auto-mapper.

A mapping assigns each source column to either a canonical field (below) or a flag
(``flag:<name>``), or leaves it ignored. Auto-mapping suggests a starting point from
header names; the user confirms/edits it (and second imports reuse a saved preset).
"""

import re

# canonical field -> header keywords that imply it
FIELD_KEYWORDS: dict[str, list[str]] = {
    "name": ["player name", "player", "name"],
    "team": ["team", "tm"],
    "position": ["pos", "position"],
    "rank": ["rk", "rank", "ecr", "overall"],
    "tier": ["tier", "tiers"],
    "position_rank": ["pos rank", "position rank", "posrk"],
    "projection": ["proj", "projection", "fpts", "points", "pts/wk", "pts wk", "ppg", "pts"],
    "adp": ["adp", "avg pick", "average draft"],
    "bye": ["bye"],
    "notes": ["notes", "note", "comment"],
}

REQUIRED_FIELDS = {"name"}
# Fields the engine consumes; anything else a user maps becomes a flag or is ignored.
KNOWN_FIELDS = set(FIELD_KEYWORDS)


def _norm_header(h: str) -> str:
    return re.sub(r"\s+", " ", h.strip().lower()).strip()


def auto_map(headers: list[str]) -> dict[str, str]:
    """Suggest {header: field} from header names. Longer keyword wins; first-come per
    field so we don't map two columns to the same canonical field."""
    used: set[str] = set()
    mapping: dict[str, str] = {}
    # score every (header, field) pair, then assign greedily by best score
    scored: list[tuple[int, str, str]] = []
    for header in headers:
        hn = _norm_header(header)
        for field, keywords in FIELD_KEYWORDS.items():
            for kw in keywords:
                if hn == kw:
                    scored.append((100 + len(kw), header, field))
                elif hn.startswith(kw) or kw in hn:
                    scored.append((len(kw), header, field))
    for _score, header, field in sorted(scored, key=lambda x: -x[0]):
        if header in mapping or field in used:
            continue
        mapping[header] = field
        used.add(field)
    # Suggest a rating for unmapped star / 1-of-5 columns (FantasyPros upside/bust/SoS).
    for header in headers:
        if header in mapping:
            continue
        hn = _norm_header(header)
        if any(kw in hn for kw in RATING_KEYWORDS):
            mapping[header] = f"flag:{_flag_name(header)}:rating"
    return mapping


def flag_target(value: str) -> str | None:
    """If a mapping value denotes a flag (``flag:rb_confidence``), return the flag name."""
    spec = parse_flag(value)
    return spec[0] if spec else None


# Header keywords that imply a 1–5 style rating (FantasyPros upside/bust/SoS, etc.).
RATING_KEYWORDS = ["upside", "bust", "sos", "boom", "floor", "ceiling", "confidence"]


def _flag_name(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _norm_header(header)).strip("_")


def parse_flag(value: str) -> tuple[str, str] | None:
    """Parse a flag mapping value into (flag_name, value_kind).

    ``flag:rb_confidence:numeric`` -> ("rb_confidence", "numeric");
    ``flag:upside:rating`` -> ("upside", "rating");
    ``flag:red_zone`` -> ("red_zone", "numeric") (kind defaults to numeric).
    """
    if not value.startswith("flag:"):
        return None
    parts = value.split(":")
    name = parts[1].strip()
    kind = parts[2].strip().lower() if len(parts) > 2 and parts[2].strip() else "numeric"
    if kind not in ("bool", "numeric", "rating"):
        kind = "numeric"
    return (name, kind) if name else None


def validate_mapping(mapping: dict[str, str]) -> list[str]:
    """Return a list of human-readable problems; empty means the mapping is usable."""
    problems: list[str] = []
    targets = [v for v in mapping.values() if v and v != "ignore"]
    fields = [t for t in targets if not t.startswith("flag:")]
    if "name" not in fields:
        problems.append("A column must be mapped to 'name'.")
    for field in fields:
        if field not in KNOWN_FIELDS:
            problems.append(f"Unknown field {field!r}.")
    dupes = {f for f in fields if fields.count(f) > 1}
    if dupes:
        problems.append(f"Multiple columns mapped to the same field: {', '.join(sorted(dupes))}.")
    return problems
