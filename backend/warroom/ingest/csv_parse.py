"""CSV parsing: bytes/text → (headers, rows) for the column-mapping wizard."""

import csv
import io


def parse_csv(text: str) -> tuple[list[str], list[dict[str, str]]]:
    """Return (headers, rows). Rows are dicts keyed by the original header strings.

    Uses csv.Sniffer to tolerate comma/tab/semicolon exports; falls back to comma.
    """
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    rows_raw = [r for r in reader if any(cell.strip() for cell in r)]
    if not rows_raw:
        return [], []
    headers = [h.strip() for h in rows_raw[0]]
    rows: list[dict[str, str]] = []
    for raw in rows_raw[1:]:
        row = {headers[i]: (raw[i].strip() if i < len(raw) else "") for i in range(len(headers))}
        rows.append(row)
    return headers, rows


def decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")
