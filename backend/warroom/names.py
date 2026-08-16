import re

_SUFFIXES = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?$")
_PUNCT = re.compile(r"[^a-z0-9 ]")
_SPACES = re.compile(r"\s+")


def normalize_name(name: str) -> str:
    """Canonical match key per DESIGN.md §3: lowercase, strip punctuation and
    generational suffixes (Jr./III/...). Phase 2's cross-source matcher builds on this."""
    n = name.lower().strip()
    n = _PUNCT.sub("", n)
    n = _SUFFIXES.sub("", n.strip())
    return _SPACES.sub(" ", n).strip()
