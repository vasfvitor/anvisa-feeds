"""Walk área → grupo → subfila → consulta and write one snapshot per day.

Snapshot layout under the snapshots directory:

    catalog.json            names of every área, grupo and subfila seen (refreshed each crawl)
    YYYY-MM-DD.jsonl.gz     one row per queued process, every subfila crawled that day
    YYYY-MM-DD.meta.json    request count, timings, subfilas crawled / failed

One request per catalog level plus one per subfila; the client's throttle keeps it at the
gateway's refill rate (1 request/s, bucket shared per source address).
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable, Iterable
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from anvisa import AnvisaError, Client, NotFoundError

BRT = ZoneInfo("America/Sao_Paulo")


def now() -> datetime:
    return datetime.now(BRT)


def today() -> date:
    return now().date()


def row_dict(row, *, area: int, grupo: int, subfila: int) -> dict:
    entrada = row.dtEntrada.astimezone(BRT).date().isoformat() if row.dtEntrada else None
    return {
        "area": area,
        "grupo": grupo,
        "subfila": subfila,
        "posicao": row.nuOrdem,
        "processo": row.numeroProcessoFormatado,
        "nuProcesso": row.nuProcesso,
        "expediente": row.expeditenteFormatado,
        "assunto": row.codAssunto,
        "dsAssunto": row.dsAssunto,
        "entrada": entrada,
    }


def crawl(
    client: Client,
    out: Path,
    *,
    day: date | None = None,
    areas: Iterable[int] | None = None,
    limit: int | None = None,
    log: Callable[[str], None] = print,
) -> dict:
    """Crawl and write the day's files. Returns the meta dict. A failed subfila is recorded in
    meta and skipped; the snapshot still holds every subfila that answered."""
    day = day or today()
    wanted = set(areas) if areas else None
    out.mkdir(parents=True, exist_ok=True)
    started = now()
    requests = 0
    catalog: dict[str, dict] = {"areas": {}, "grupos": {}, "subfilas": {}}
    rows: list[dict] = []
    crawled: list[int] = []
    failed: list[dict] = []

    for area in client.fila.areas():
        if wanted and area.id not in wanted:
            continue
        catalog["areas"][str(area.id)] = area.descricao
        grupos = client.fila.grupos(area.id)
        requests += 1
        for grupo in grupos:
            catalog["grupos"][str(grupo.id)] = {"descricao": grupo.descricao, "area": area.id}
            subfilas = client.fila.subfilas(grupo.id)
            requests += 1
            for sub in subfilas:
                catalog["subfilas"][str(sub.id)] = {
                    "descricao": sub.descricao,
                    "grupo": grupo.id,
                    "area": area.id,
                }
                if limit is not None and len(crawled) + len(failed) >= limit:
                    continue
                requests += 1
                try:
                    queue = client.fila.consulta(sub.id)
                except NotFoundError:
                    # a subfila with nothing queued answers an empty-bodied 404 (88 of 314 on
                    # 2026-09-06); anvisa >= 0.3 returns [] itself, older versions raise
                    queue = []
                except AnvisaError as exc:
                    failed.append({"subfila": sub.id, "error": str(exc)})
                    log(f"subfila {sub.id}: {exc}")
                    continue
                crawled.append(sub.id)
                rows.extend(
                    row_dict(r, area=area.id, grupo=grupo.id, subfila=sub.id) for r in queue
                )
                log(f"subfila {sub.id} ({sub.descricao}): {len(queue)} rows")

    requests += 1  # the initial areas() call
    finished = now()
    meta = {
        "date": day.isoformat(),
        "started": started.isoformat(),
        "finished": finished.isoformat(),
        "seconds": round((finished - started).total_seconds()),
        "requests": requests,
        "rows": len(rows),
        "subfilas_total": len(catalog["subfilas"]),
        "subfilas_crawled": len(crawled),
        "crawled": crawled,
        "failed": failed,
    }
    with gzip.open(out / f"{day.isoformat()}.jsonl.gz", "wt", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out / f"{day.isoformat()}.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return meta


def snapshot_days(snapshots: Path) -> list[date]:
    """Every day that has a snapshot, oldest first."""
    return sorted(date.fromisoformat(p.name[:10]) for p in snapshots.glob("*.jsonl.gz"))


def load_snapshot(snapshots: Path, day: date) -> dict[int, list[dict]]:
    """Rows of one day grouped by subfila id, in queue order. A crawled subfila with an empty
    queue is present with an empty list (from meta), so "empty" and "not crawled" differ."""
    crawled = load_meta(snapshots, day).get("crawled", [])
    queues: dict[int, list[dict]] = {sub: [] for sub in crawled}
    with gzip.open(snapshots / f"{day.isoformat()}.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            queues.setdefault(row["subfila"], []).append(row)
    for queue in queues.values():
        queue.sort(key=lambda r: r["posicao"] or 0)
    return queues


def load_meta(snapshots: Path, day: date) -> dict:
    return json.loads((snapshots / f"{day.isoformat()}.meta.json").read_text(encoding="utf-8"))


def load_catalog(snapshots: Path) -> dict:
    path = snapshots / "catalog.json"
    if not path.exists():
        return {"areas": {}, "grupos": {}, "subfilas": {}}
    return json.loads(path.read_text(encoding="utf-8"))
