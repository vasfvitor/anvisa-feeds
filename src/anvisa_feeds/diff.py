"""What changed in each queue between two snapshots."""

from __future__ import annotations


def key(row: dict) -> str:
    """A process can sit in one queue twice with two petitions (seen live: 25351.316782/2020-07
    with expedientes 0882409/26-3 and 0913447/26-9), so the identity is process + expediente."""
    return f"{row.get('nuProcesso') or row.get('processo') or ''}|{row.get('expediente') or ''}"


def diff_queue(prev: list[dict], curr: list[dict]) -> list[dict]:
    """Events for one subfila: entered, left, moved. Sorted by current position, then by the
    position the process used to have."""
    before = {key(r): r for r in prev}
    after = {key(r): r for r in curr}
    events: list[dict] = []
    for k, row in after.items():
        old = before.get(k)
        if old is None:
            events.append(
                {"type": "entered", "processo": row["processo"], "para": row["posicao"], "row": row}
            )
        elif old["posicao"] != row["posicao"]:
            events.append(
                {
                    "type": "moved",
                    "processo": row["processo"],
                    "de": old["posicao"],
                    "para": row["posicao"],
                    "row": row,
                }
            )
    for k, row in before.items():
        if k not in after:
            events.append(
                {"type": "left", "processo": row["processo"], "de": row["posicao"], "row": row}
            )
    order = {"entered": 0, "moved": 1, "left": 2}
    events.sort(key=lambda e: (e.get("para") or 10**9, order[e["type"]], e.get("de") or 0))
    return events


def diff_snapshots(
    prev: dict[int, list[dict]], curr: dict[int, list[dict]]
) -> dict[int, list[dict]]:
    """Events per subfila. A subfila missing from either day (not crawled, or failed) yields
    nothing: absence of data is not a change."""
    return {sub: diff_queue(prev[sub], curr[sub]) for sub in sorted(curr) if sub in prev}


def summary(events: list[dict]) -> str:
    counts = {"entered": 0, "moved": 0, "left": 0}
    for e in events:
        counts[e["type"]] += 1
    parts = []
    if counts["entered"]:
        parts.append(
            f"{counts['entered']} entrou"
            if counts["entered"] == 1
            else f"{counts['entered']} entraram"
        )
    if counts["left"]:
        parts.append(
            f"{counts['left']} saiu" if counts["left"] == 1 else f"{counts['left']} saíram"
        )
    if counts["moved"]:
        parts.append(
            f"{counts['moved']} mudaram de posição" if counts["moved"] > 1 else "1 mudou de posição"
        )
    return ", ".join(parts) if parts else "sem mudanças"
