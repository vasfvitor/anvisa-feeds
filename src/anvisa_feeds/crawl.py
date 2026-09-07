"""Walk área → grupo → subfila → consulta and write one snapshot per day.

Snapshot layout under the snapshots directory:

    catalog.json            names of every área, grupo and subfila seen (refreshed each crawl)
    YYYY-MM-DD.jsonl.gz     one line per crawled subfila: {subfila, area, grupo, rows: [...]}
    YYYY-MM-DD.meta.json    request count, timings, subfilas crawled / failed

A subfila with an empty `rows` was crawled and has nothing queued; a subfila absent from the
file was not crawled that day. One request per subfila, plus one per catalog level on the
days the catalog is re-walked (Mondays, or when catalog.json is missing); the client's
throttle keeps it at the gateway's refill rate (1 request/s, bucket shared per source
address).
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable, Iterable
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from anvisa import AnvisaError, Client

BRT = ZoneInfo("America/Sao_Paulo")


def now() -> datetime:
    return datetime.now(BRT)


def today() -> date:
    return now().date()


def dump_json(path: Path, data, **kwargs) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, **kwargs) + "\n", encoding="utf-8")


def row_dict(row) -> dict:
    entrada = row.dtEntrada.astimezone(BRT).date().isoformat() if row.dtEntrada else None
    return {
        "posicao": row.nuOrdem,
        "processo": row.numeroProcessoFormatado,
        "nuProcesso": row.nuProcesso,
        "expediente": row.expeditenteFormatado,
        "assunto": row.codAssunto,
        "dsAssunto": row.dsAssunto,
        "entrada": entrada,
    }


def write_snapshot(out: Path, day: date, queues: Iterable[dict]) -> None:
    with gzip.open(out / f"{day.isoformat()}.jsonl.gz", "wt", encoding="utf-8") as fh:
        for queue in queues:
            fh.write(json.dumps(queue, ensure_ascii=False) + "\n")


def walk_catalog(client: Client, wanted: set[int] | None = None) -> dict:
    """área → grupo → subfila names and ids: 1 + areas + grupos requests."""
    catalog: dict[str, dict] = {"areas": {}, "grupos": {}, "subfilas": {}}
    for area in client.fila.areas():
        if wanted and area.id not in wanted:
            continue
        catalog["areas"][str(area.id)] = area.descricao
        for grupo in client.fila.grupos(area.id):
            catalog["grupos"][str(grupo.id)] = {"descricao": grupo.descricao, "area": area.id}
            for sub in client.fila.subfilas(grupo.id):
                catalog["subfilas"][str(sub.id)] = {
                    "descricao": sub.descricao,
                    "grupo": grupo.id,
                    "area": area.id,
                }
    return catalog


def crawl(
    client: Client,
    out: Path,
    *,
    day: date | None = None,
    areas: Iterable[int] | None = None,
    refresh_catalog: bool | None = None,
    log: Callable[[str], None] = print,
) -> dict:
    """Crawl and write the day's files. Returns the meta dict. A failed subfila is recorded in
    meta and skipped; the snapshot still holds every subfila that answered.

    The catalog is re-walked when `refresh_catalog` is true, or by default on Mondays and
    whenever catalog.json is missing; other days reuse it, which saves the ~70 catalog
    requests and means a new subfila is noticed within a week."""
    day = day or today()
    wanted = set(areas) if areas else None
    out.mkdir(parents=True, exist_ok=True)
    started = now()
    if refresh_catalog is None:
        refresh_catalog = day.weekday() == 0 or not (out / "catalog.json").exists()
    if refresh_catalog:
        catalog = walk_catalog(client, wanted)
        catalog_requests = 1 + len(catalog["areas"]) + len(catalog["grupos"])
    else:
        catalog = load_catalog(out)
        catalog_requests = 0
    subfilas = {
        int(sub): info
        for sub, info in catalog["subfilas"].items()
        if not wanted or info["area"] in wanted
    }

    queues: list[dict] = []
    failed: list[dict] = []
    for sub, info in subfilas.items():
        try:
            rows = client.fila.consulta(sub)  # [] when nothing is queued
        except AnvisaError as exc:
            failed.append({"subfila": sub, "error": str(exc)})
            log(f"subfila {sub}: {exc}")
            continue
        queues.append(
            {
                "subfila": sub,
                "area": info["area"],
                "grupo": info["grupo"],
                "rows": [row_dict(r) for r in rows],
            }
        )
        log(f"subfila {sub} ({info['descricao']}): {len(rows)} rows")

    finished = now()
    meta = {
        "date": day.isoformat(),
        "started": started.isoformat(),
        "finished": finished.isoformat(),
        "seconds": round((finished - started).total_seconds()),
        "catalog_refreshed": refresh_catalog,
        "requests": catalog_requests + len(queues) + len(failed),
        "rows": sum(len(q["rows"]) for q in queues),
        "subfilas_total": len(subfilas),
        "subfilas_crawled": len(queues),
        "failed": failed,
    }
    write_snapshot(out, day, queues)
    dump_json(out / f"{day.isoformat()}.meta.json", meta, indent=2)
    if refresh_catalog:
        dump_json(out / "catalog.json", catalog, indent=2, sort_keys=True)
    return meta


def snapshot_days(snapshots: Path) -> list[date]:
    """Every day that has a snapshot, oldest first."""
    return sorted(date.fromisoformat(p.name[:10]) for p in snapshots.glob("*.jsonl.gz"))


def load_snapshot(snapshots: Path, day: date) -> dict[int, list[dict]]:
    """Queues of one day by subfila id, rows in queue order. Crawled-and-empty subfilas are
    present with an empty list; subfilas not crawled that day are absent."""
    with gzip.open(snapshots / f"{day.isoformat()}.jsonl.gz", "rt", encoding="utf-8") as fh:
        queues = [json.loads(line) for line in fh]
    return {q["subfila"]: sorted(q["rows"], key=lambda r: r["posicao"] or 0) for q in queues}


def load_meta(snapshots: Path, day: date) -> dict:
    return json.loads((snapshots / f"{day.isoformat()}.meta.json").read_text(encoding="utf-8"))


def load_catalog(snapshots: Path) -> dict:
    path = snapshots / "catalog.json"
    if not path.exists():
        return {"areas": {}, "grupos": {}, "subfilas": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def describe(catalog: dict, sub: int) -> tuple[str, str, str]:
    """(subfila name, grupo name, área name) for a subfila id, with readable fallbacks."""
    info = catalog["subfilas"].get(str(sub), {})
    grupo = catalog["grupos"].get(str(info.get("grupo")), {})
    return (
        info.get("descricao") or f"subfila {sub}",
        grupo.get("descricao") or "?",
        catalog["areas"].get(str(info.get("area"))) or "?",
    )
