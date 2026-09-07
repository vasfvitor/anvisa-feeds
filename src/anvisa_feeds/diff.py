"""What changed in each queue between two snapshots."""

from __future__ import annotations

from collections import Counter

FAR = 10**9  # sorts events without a current position (left) after everything else
ORDER = {"entered": 0, "moved": 1, "left": 2}
WORDS = [
    ("entered", "entrou", "entraram"),
    ("left", "saiu", "saíram"),
    ("moved", "mudou de posição", "mudaram de posição"),
]


def key(row: dict) -> str:
    """A process can sit in one queue twice with two petitions (seen live: 25351.316782/2020-07
    with expedientes 0882409/26-3 and 0913447/26-9), so the identity is process + expediente."""
    return f"{row.get('nuProcesso') or row.get('processo') or ''}|{row.get('expediente') or ''}"


def event(kind: str, row: dict, de: int | None = None, para: int | None = None) -> dict:
    return {
        "type": kind,
        "processo": row.get("processo"),
        "expediente": row.get("expediente"),
        "de": de,
        "para": para,
    }


def diff_queue(prev: list[dict], curr: list[dict]) -> list[dict]:
    """Events for one subfila: entered, left, moved. Sorted by current position, then by the
    position the process used to have."""
    before = {key(r): r for r in prev}
    after = {key(r): r for r in curr}
    events = []
    for k, row in after.items():
        old = before.get(k)
        if old is None:
            events.append(event("entered", row, para=row["posicao"]))
        elif old["posicao"] != row["posicao"]:
            events.append(event("moved", row, old["posicao"], row["posicao"]))
    events += [event("left", row, de=row["posicao"]) for k, row in before.items() if k not in after]
    events.sort(
        key=lambda e: (e["para"] if e["para"] is not None else FAR, ORDER[e["type"]], e["de"] or 0)
    )
    return events


def diff_snapshots(
    prev: dict[int, list[dict]], curr: dict[int, list[dict]]
) -> dict[int, list[dict]]:
    """Events per subfila. A subfila missing from either day (not crawled, or failed) yields
    nothing: absence of data is not a change."""
    return {sub: diff_queue(prev[sub], curr[sub]) for sub in sorted(curr) if sub in prev}


def summary(events: list[dict]) -> str:
    counts = Counter(e["type"] for e in events)
    parts = [f"{n} {one if n == 1 else many}" for kind, one, many in WORDS if (n := counts[kind])]
    return ", ".join(parts) or "sem mudanças"
