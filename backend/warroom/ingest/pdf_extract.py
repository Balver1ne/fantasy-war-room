"""PDF text extraction for Fantasy Headliners layouts.

pdfplumber table extraction is flaky on these multi-column layouts (DESIGN.md §4), so
we parse the extracted *text* line by line with layout-specific record patterns. Output
is the same (headers, rows, suggested_mapping) shape the CSV importer consumes, so a PDF
flows through the identical map → match → resolve → commit pipeline, with a mandatory
preview in between. Anything that parses badly falls back to the paste parser.
"""

import io
import re
from collections.abc import Callable
from dataclasses import dataclass, field

import pdfplumber

# One ranking record: "1 Bijan Robinson RB1 ATL 11" (rank name POS+rank team bye)
_RANK_REC = re.compile(
    r"(\d{1,3})\s+([A-Z][A-Za-z.'\-]+(?:\s+[A-Za-z.'\-]+)*?)\s+([A-Za-z]{1,3}\d+)\s+([A-Za-z]{2,4})\s+(\d{1,2})"
)
# One "list" record: "JARED GOFF DET QB16" (NAME TEAM POS+rank) — uppercase names
_LIST_REC = re.compile(
    r"([A-Z][A-Z.'\-]*(?:\s+[A-Z.'\-]+)*?)\s+([A-Z]{2,4})\s+([A-Z]{1,3}\d+)"
)
# One sleeper/breakout/bust record: "QB KYLER MURRAY MIN JAKE" (POS NAME TEAM ANALYST)
_SBB_REC = re.compile(
    r"\b(QB|RB|WR|TE|K|DEF|DST)\s+([A-Z][A-Z.'\-]*(?:\s+[A-Z.'\-]+)*?)\s+([A-Z]{2,4})\s+(JAKE|KYLE)"
)


_SECTION_WORDS = {"SLEEPER", "BREAKOUT", "BUST", "PICK", "PICKS", "VALUE", "RANKINGS",
                  "SLEEPERS", "BREAKOUTS", "BUSTS"}


def _looks_like_player(name: str, team: str) -> bool:
    """Reject section-header / abbreviation noise that the record regexes can pick up
    (e.g. 'QB 3 PICKS' or a bare team code landing in the name slot). Real list-layout
    names are two-part, so require a space and a section-free team code."""
    name = name.strip()
    if " " not in name:
        return False
    if team.strip().upper() in _SECTION_WORDS:
        return False
    return True


@dataclass
class PdfExtraction:
    layout: str
    headers: list[str]
    rows: list[dict[str, str]]
    suggested_mapping: dict[str, str]
    raw_text: str
    page_count: int
    notes: list[str] = field(default_factory=list)


def extract_pages(data: bytes) -> list[str]:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return [(p.extract_text() or "") for p in pdf.pages]


def detect_layout(full_text: str) -> str:
    t = full_text.upper()
    if "FLEX RANKINGS" in t or "REDRAFT RANKINGS" in t:
        return "tfh_rankings"
    if "SLEEPERS" in t and "BREAKOUTS" in t and "BUSTS" in t:
        return "tfh_sbb"
    if "HANDCUFF" in t:
        return "tfh_handcuffs"
    if "VALUE" in t and "PICK" in t:
        return "tfh_value"
    return "generic"


def _parse_rankings(pages: list[str]) -> tuple[list[str], list[dict[str, str]], dict[str, str]]:
    """Flex/overall board only. The per-position pages that follow restart their rank
    numbering (and repeat players), so a rank we've already seen marks the section
    boundary and we stop — keeping one clean set of overall ranks."""
    rows: list[dict[str, str]] = []
    seen_rank: set[int] = set()
    headers = ["rank", "name", "position", "team", "bye"]
    mapping = {h: h for h in headers}
    for page in pages:
        for line in page.splitlines():
            for m in _RANK_REC.finditer(line):
                rank, name, pos, team, bye = m.groups()
                ri = int(rank)
                if ri in seen_rank:
                    return headers, rows, mapping
                seen_rank.add(ri)
                rows.append({"rank": rank, "name": name.strip(), "position": pos,
                             "team": team, "bye": bye})
    return headers, rows, mapping


def _parse_list(
    pages: list[str], flag_name: str
) -> tuple[list[str], list[dict[str, str]], dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for page in pages:
        for line in page.splitlines():
            for m in _LIST_REC.finditer(line):
                name, team, pos = m.groups()
                if not _looks_like_player(name, team):
                    continue
                key = (name.strip(), pos)
                if key in seen:
                    continue
                seen.add(key)
                rows.append({"name": name.strip().title(), "team": team,
                             "position": pos, flag_name: "Y"})
    headers = ["name", "team", "position", flag_name]
    mapping = {"name": "name", "team": "team", "position": "position",
               flag_name: f"flag:{flag_name}:bool"}
    return headers, rows, mapping


def _parse_sbb(pages: list[str]) -> tuple[list[str], list[dict[str, str]], dict[str, str]]:
    cols = ["sleeper", "breakout", "bust"]
    rows: list[dict[str, str]] = []
    for page in pages:
        for line in page.splitlines():
            matches = list(_SBB_REC.finditer(line))
            for i, m in enumerate(matches):
                pos, name, team, _analyst = m.groups()
                if not _looks_like_player(name, team):
                    continue
                flag = cols[i] if i < len(cols) else cols[-1]
                rows.append({"name": name.strip().title(), "team": team, "position": pos,
                             "sleeper": "Y" if flag == "sleeper" else "",
                             "breakout": "Y" if flag == "breakout" else "",
                             "bust": "Y" if flag == "bust" else ""})
    headers = ["name", "team", "position", "sleeper", "breakout", "bust"]
    mapping = {"name": "name", "team": "team", "position": "position",
               "sleeper": "flag:sleeper:bool", "breakout": "flag:breakout:bool",
               "bust": "flag:bust:bool"}
    return headers, rows, mapping


_PARSERS: dict[str, Callable] = {
    "tfh_rankings": _parse_rankings,
    "tfh_value": lambda pages: _parse_list(pages, "value_pick"),
    "tfh_handcuffs": lambda pages: _parse_list(pages, "handcuff"),
    "tfh_sbb": _parse_sbb,
}


def extract(data: bytes, layout: str | None = None) -> PdfExtraction:
    pages = extract_pages(data)
    raw_text = "\n".join(pages)
    layout = layout or detect_layout(raw_text)
    parser = _PARSERS.get(layout)
    notes: list[str] = []
    if parser is None:
        notes.append(f"No parser for layout {layout!r}; use the paste fallback.")
        headers, rows, mapping = [], [], {}
    else:
        headers, rows, mapping = parser(pages)
    if not rows:
        notes.append("No rows extracted — the layout may need the paste fallback.")
    return PdfExtraction(
        layout=layout, headers=headers, rows=rows, suggested_mapping=mapping,
        raw_text=raw_text, page_count=len(pages), notes=notes,
    )
