"""Monthly snapshots of the CMED price list, beside the daily fila snapshots.

CMED (the medicine price regulator, with its secretariat at ANVISA) publishes a list of maximum
prices per presentation once a month; ANVISA republishes it as two CSVs on its open-data
server. `anvisa.dados.cmed` reads and merges them; this module decides when a new month is out
(the files' ETags), writes one snapshot per month and keeps the raw files for the Release.

Layout under the CMED snapshots directory (`snapshots/cmed/`, invisible to the fila globs,
which only read `snapshots/*.jsonl.gz`):

    YYYYMMDD.jsonl.xz    line 1 {"columns": [...]}, then one JSON array per presentation
                         (GGREM), the merged row of anvisa.dados.cmed in that column order
    YYYYMMDD.meta.json   the files' ETag, Last-Modified, size and hash; row counts; fetch time

The stamp is the day of the PMC file's Last-Modified, in Brasília. Arrays under xz: a month is
about 3 MB (26,635 rows of 102 columns), against 10 MB as gzipped objects.
"""

from __future__ import annotations

import json
import lzma
from collections.abc import Callable
from pathlib import Path

import httpx
from anvisa.dados import cmed as reader
from anvisa.dados.catalog import BASE_URL
from anvisa.dados.fetch import cmed_stamp, download_url, http_client

from .crawl import dump_json, now

RELEASE_TAG = "cmed-{stamp}"  # the GitHub Release that keeps the month's raw files
# a month with fewer rows than this share of the previous one is refused: a truncated or partial
# file would otherwise read as thousands of presentations leaving the list
MIN_ROWS_RATIO = 0.95


def stamps(snapshots: Path) -> list[str]:
    """Every month snapshotted, oldest first."""
    return sorted(p.name[:8] for p in Path(snapshots).glob("????????.jsonl.xz"))


def load_rows(snapshots: Path, stamp: str) -> dict[str, dict]:
    """One month's rows keyed by GGREM."""
    with lzma.open(Path(snapshots) / f"{stamp}.jsonl.xz", "rt", encoding="utf-8") as fh:
        columns = json.loads(next(fh))["columns"]
        rows = (dict(zip(columns, json.loads(line), strict=True)) for line in fh if line.strip())
        return {r["ggrem"]: r for r in rows}


def load_meta(snapshots: Path, stamp: str) -> dict:
    return json.loads((Path(snapshots) / f"{stamp}.meta.json").read_text(encoding="utf-8"))


def latest_meta(snapshots: Path) -> dict | None:
    known = stamps(snapshots)
    return load_meta(snapshots, known[-1]) if known else None


def crawl(
    out: Path,
    *,
    raw_dir: Path,
    http: httpx.Client | None = None,
    log: Callable[[str], None] = print,
    min_rows_ratio: float = MIN_ROWS_RATIO,
) -> dict | None:
    """Fetch the two files when either changed since the latest snapshot (conditional on
    the recorded ETags), write the month's snapshot and meta, keep the raw files in
    `raw_dir`. None when both answered 304: nothing new this month. Exits without writing
    when the new month has fewer than `min_rows_ratio` of the previous month's rows."""
    out, raw_dir = Path(out), Path(raw_dir)
    out.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    previous = latest_meta(out)
    known = {f["name"]: f for f in (previous or {}).get("files", [])}
    own = http is None
    http = http or http_client()
    try:
        fetched = {}
        for kind, file in reader.FILES.items():
            before = known.get(file) or {}
            log(f"GET {BASE_URL}{file}")
            fetched[kind] = download_url(
                http,
                BASE_URL + file,
                raw_dir / file,
                name=file,
                etag=before.get("etag"),
                last_modified=before.get("last_modified"),
            )
            if fetched[kind] is None:
                log(f"  not modified (etag {before.get('etag')})")
        if all(s is None for s in fetched.values()):
            return None
        for kind, file in reader.FILES.items():  # the pair is one cut: refetch the 304 one
            if fetched[kind] is None:
                fetched[kind] = download_url(http, BASE_URL + file, raw_dir / file, name=file)
    finally:
        if own:
            http.close()
    pmc = fetched["pmc"]
    assert pmc is not None and fetched["pmvg"] is not None
    stamp, publicado_em = cmed_stamp(pmc.last_modified)
    if stamp is None:
        raise SystemExit(f"{reader.FILES['pmc']}: no Last-Modified header, cannot name the month")
    rows, stats = reader.read_merged(
        raw_dir / reader.FILES["pmc"], raw_dir / reader.FILES["pmvg"], publicado_em=publicado_em
    )
    if previous and stats.rows < previous["rows"] * min_rows_ratio:
        raise SystemExit(
            f"snapshot {stamp}: {stats.rows} rows against {previous['rows']} in "
            f"{previous['stamp']}; refusing it (rerun with a lower --min-rows-ratio if the list "
            "really shrank)"
        )
    columns = list(reader.COLUMNS)
    with lzma.open(out / f"{stamp}.jsonl.xz", "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"columns": columns}) + "\n")
        for row in rows:
            fh.write(json.dumps([row[c] for c in columns], ensure_ascii=False) + "\n")
    meta = {
        "stamp": stamp,
        "publicado_em": publicado_em,
        "fetched": now().isoformat(),
        "rows": stats.rows,
        "only_pmc": stats.only_pmc,
        "only_pmvg": stats.only_pmvg,
        "files": [
            {
                "name": s.name,
                "url": s.url,
                "etag": s.etag,
                "last_modified": s.last_modified,
                "bytes": s.bytes,
                "sha256": s.sha256,
            }
            for s in (pmc, fetched["pmvg"])
        ],
        "release": RELEASE_TAG.format(stamp=stamp),
    }
    dump_json(out / f"{stamp}.meta.json", meta, indent=2)
    log(
        f"snapshot {stamp}: {stats.rows} rows "
        f"({stats.only_pmc} only PMC, {stats.only_pmvg} only PMVG)"
    )
    return meta
