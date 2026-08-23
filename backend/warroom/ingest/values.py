"""Lenient value coercion for imported cells."""

import re

_TRUE = {"y", "yes", "true", "1", "x", "✓", "t"}
_FALSE = {"n", "no", "false", "0", "", "-"}


def to_int(value) -> int | None:
    if value is None:
        return None
    m = re.search(r"-?\d+", str(value))
    return int(m.group()) if m else None


def to_float(value) -> float | None:
    if value is None:
        return None
    m = re.search(r"-?\d+(\.\d+)?", str(value).replace(",", ""))
    return float(m.group()) if m else None


def to_bool(value) -> bool | None:
    if value is None:
        return None
    v = str(value).strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return None
