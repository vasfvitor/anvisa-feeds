"""Registration status and ANVISA measures per medicine, for the CMED products in cmed/dados.

Both come from the anvisa-api open data (Parquet on GitHub Pages, described by its manifest):
`medicamentos_por_produto` (one row per medicine: `ativo`, `vencimento`) and `medidas` (one row
per dossiê × product: suspensions, recalls, bans; area 1 is medicines). Both carry the 9-digit
registro, the same `registro_produto` as the CMED list, so the join is exact. The files are
downloaded whole (Pages does not do ranges well) and read locally with DuckDB, which needs no
extension for a local Parquet.

The medidas carry no lot: a recall of some lots and a ban of the product look alike here, so the
portal says the measure may cover only some lots.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx

MANIFEST_URL = "https://vasfvitor.github.io/anvisa-api/manifest.json"
TABLES = ("medicamentos_por_produto", "medidas")
AREA_MEDICAMENTO = 1


def fetch(
    cache: Path, *, manifest_url: str = MANIFEST_URL, http: httpx.Client | None = None
) -> dict[str, Path]:
    """Download the two tables of the current build into `cache`; their paths by table name."""
    own = http is None
    http = http or httpx.Client(timeout=60, follow_redirects=True)
    try:
        manifest = http.get(manifest_url)
        manifest.raise_for_status()
        tables = manifest.json()["tables"]  # {name: {path, rows, columns, …}}
        cache.mkdir(parents=True, exist_ok=True)
        out = {}
        for name in TABLES:
            r = http.get(httpx.URL(manifest_url).join(tables[name]["path"]))
            r.raise_for_status()
            out[name] = cache / f"{name}.parquet"
            out[name].write_bytes(r.content)
        return out
    finally:
        if own:
            http.close()


def load(paths: dict[str, Path]) -> dict[str, dict]:
    """By registro_produto: `ativo`, `vencimento` (YYYY-MM or None) and `medidas`, the medicine
    measures that cite the registro, newest first."""
    import duckdb  # only the build that reads these tables needs it

    con = duckdb.connect()
    out: dict[str, dict] = {}
    rows = con.execute(
        "SELECT registro_produto, ativo, strftime(vencimento, '%Y-%m') "
        "FROM read_parquet(?) WHERE registro_produto IS NOT NULL",
        [str(paths["medicamentos_por_produto"])],
    ).fetchall()
    for registro, ativo, vencimento in rows:
        out[registro] = {"ativo": bool(ativo), "vencimento": vencimento, "medidas": []}
    medidas = con.execute(
        "SELECT r AS registro, processo, acoes, atividades, strftime(ultima, '%Y-%m-%d') "
        "FROM read_parquet(?), unnest(registros) AS u(r) "
        "WHERE area_codigo = ? ORDER BY ultima DESC, dossie DESC",
        [str(paths["medidas"]), AREA_MEDICAMENTO],
    ).fetchall()
    for registro, processo, acoes, atividades, data in medidas:
        item = out.get(registro)
        if item is None:  # a measure on a registro the medicines table does not know
            continue
        item["medidas"].append(
            {"data": data, "acoes": acoes, "atividades": atividades, "processo": processo}
        )
    return out


def carregar(
    cache: Path, *, manifest_url: str = MANIFEST_URL, log: Callable[[str], None] = print
) -> dict[str, dict] | None:
    """fetch + load; None, with a line in the log, when the source cannot be read: the feeds
    and prices still build, and the portal shows nothing about the registration."""
    try:
        return load(fetch(cache, manifest_url=manifest_url))
    except Exception as e:  # noqa: BLE001 - any failure here must not stop the build
        log(f"situação dos registros: fonte indisponível ({type(e).__name__}: {e})")
        return None
