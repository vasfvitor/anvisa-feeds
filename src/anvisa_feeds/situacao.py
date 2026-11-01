"""Registration status and ANVISA measures per medicine, for the CMED products in cmed/dados.

Both come from the anvisa-api open data (Parquet on GitHub Pages, described by its manifest):
`medicamentos_por_produto` (one row per medicine: `ativo`, `vencimento`) and `medidas` (one row
per dossiê × product: suspensions, recalls, bans; area 1 is medicines). Both carry the 9-digit
registro, the same `registro_produto` as the CMED list, so the join is exact. The files are
downloaded whole (Pages does not do ranges well) and read locally with DuckDB, which needs no
extension for a local Parquet.

The medidas carry no lot: a recall of some lots and a ban of the product look alike here, so the
portal says the measure may cover only some lots.

The official names of the substâncias (DCB) come the same way, from `substancias_dcb`, which is
under its own license, so the portal gets them in a file of their own.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import httpx

MANIFEST_URL = "https://vasfvitor.github.io/anvisa-api/manifest.json"
TABLES = ("medicamentos_por_produto", "medidas")
TABELA_DCB = "substancias_dcb"
AREA_MEDICAMENTO = 1


@dataclass(frozen=True)
class Situacao:
    """What carregar read: the anvisa-api build it came from and the data by registro."""

    fonte: dict  # {"build_id", "built_at"} of the anvisa-api manifest
    registros: dict[str, dict]


@dataclass(frozen=True)
class Dcb:
    """What carregar_dcb read: where the names came from and their license, and the official
    names of each CMED substância with every part in the DCB, in the order of its parts."""

    fonte: dict  # {"build_id", "built_at", "titulo", "licenca"}
    nomes: dict[str, list[str]]


def _baixar(
    cache: Path, tabelas: tuple[str, ...], manifest_url: str, http: httpx.Client | None
) -> tuple[dict[str, Path], dict]:
    """Download `tabelas` of the current build into `cache`: their paths by table name, and
    the manifest they came from."""
    own = http is None
    http = http or httpx.Client(timeout=60, follow_redirects=True)
    try:
        manifest = http.get(manifest_url)
        manifest.raise_for_status()
        data = manifest.json()
        tables = data["tables"]  # {name: {path, rows, columns, …}}
        cache.mkdir(parents=True, exist_ok=True)
        out = {}
        for name in tabelas:
            r = http.get(httpx.URL(manifest_url).join(tables[name]["path"]))
            r.raise_for_status()
            out[name] = cache / f"{name}.parquet"
            out[name].write_bytes(r.content)
        return out, data
    finally:
        if own:
            http.close()


def fetch(
    cache: Path, *, manifest_url: str = MANIFEST_URL, http: httpx.Client | None = None
) -> tuple[dict[str, Path], dict]:
    """Download the two tables of the current build into `cache`: their paths by table name,
    and the build they came from ({"build_id", "built_at"})."""
    out, data = _baixar(cache, TABLES, manifest_url, http)
    return out, {"build_id": data.get("build_id"), "built_at": data.get("built_at")}


def fetch_dcb(
    cache: Path, *, manifest_url: str = MANIFEST_URL, http: httpx.Client | None = None
) -> tuple[Path, dict]:
    """Download `substancias_dcb` into `cache`: its path, and the build, the list's title and
    the license to cite with the names. The title drops ANVISA's "- VIGENTE": the table comes
    from a copy kept by hand, which can lag the version in force."""
    out, data = _baixar(cache, (TABELA_DCB,), manifest_url, http)
    tables = data["tables"]
    return out[TABELA_DCB], {
        "build_id": data.get("build_id"),
        "built_at": data.get("built_at"),
        "titulo": tables["dcb"]["source"]["name"].removesuffix(" - VIGENTE"),
        "licenca": tables[TABELA_DCB]["license"],
    }


def load_dcb(path: Path) -> dict[str, list[str]]:
    """The official names of each substância with every part in the DCB. A substância with
    only some of them is left out: the portal says nothing about it."""
    import duckdb  # only the build that reads these tables needs it

    rows = duckdb.connect().execute(
        "SELECT substancia, dcb_denominacoes FROM read_parquet(?) WHERE todas_na_dcb", [str(path)]
    )
    return dict(rows.fetchall())


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
) -> Situacao | None:
    """fetch + load; None, with a line in the log, when the source cannot be read. The feeds and
    prices still build, and cmed/dados then says so (`situacao_fonte: null`) instead of looking
    like a day with nothing to report; the workflow turns that into a red run."""
    try:
        paths, fonte = fetch(cache, manifest_url=manifest_url)
        return Situacao(fonte=fonte, registros=load(paths))
    except Exception as e:  # noqa: BLE001 - any failure here must not stop the build
        log(f"situação dos registros: fonte indisponível ({type(e).__name__}: {e})")
        return None


def carregar_dcb(
    cache: Path, *, manifest_url: str = MANIFEST_URL, log: Callable[[str], None] = print
) -> Dcb | None:
    """fetch_dcb + load_dcb; None, with a line in the log, when the source cannot be read. On
    its own, so that it and the registration status cannot take each other down."""
    try:
        path, fonte = fetch_dcb(cache, manifest_url=manifest_url)
        return Dcb(fonte=fonte, nomes=load_dcb(path))
    except Exception as e:  # noqa: BLE001 - any failure here must not stop the build
        log(f"nomes oficiais (DCB): fonte indisponível ({type(e).__name__}: {e})")
        return None
