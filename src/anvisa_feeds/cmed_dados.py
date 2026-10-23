"""CMED data for the public portal: one JSON per product (registro_produto) with the maximum
consumer price (PMC) of each presentation at every ICMS rate, plus a search index and the schema.

Only presentations sold in pharmacies (with some PMC) go in; hospital-only ones have no PMC. Prices
stay as the list gives them, in centavos. Written under site/cmed/dados/ by build_cmed.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from anvisa.dados import cmed as reader

SCHEMA = Path(__file__).with_name("cmed_dados_schema.md")
# "17,5" in the list → "17.5" in the JSON keys; column suffix "17_5"
ALIQUOTAS = [(a.replace(",", "."), a.replace(",", "_")) for a in reader.ALIQUOTAS]


def _mais_comum(values: list[str | None]) -> str | None:
    found = Counter(v for v in values if v)
    return found.most_common(1)[0][0] if found else None


def _precos(row: dict, *, alc: bool) -> dict[str, int]:
    out = {}
    for chave, sufixo in ALIQUOTAS:
        if alc and chave == "0":
            continue  # 0% has no ALC variant
        valor = row.get(f"pmc_{sufixo}_alc" if alc else f"pmc_{sufixo}")
        if valor is not None:
            out[chave] = valor
    return out


def apresentacao(row: dict) -> dict:
    return {
        "ggrem": row["ggrem"],
        "apresentacao": row["apresentacao"],
        "eans": [row[k] for k in ("ean_1", "ean_2", "ean_3") if row.get(k)],
        "regime_preco": row["regime_preco"],
        "comercializado": row["comercializacao"] == "S",
        "icms_0": row["icms_0"] == "S",
        "pmc": _precos(row, alc=False),
        "pmc_alc": _precos(row, alc=True),
    }


def produtos(rows: dict[str, dict], *, stamp: str, publicado_em: str) -> list[dict]:
    """Group presentations with a PMC by registro_produto, sorted by it."""
    grupos: dict[str, list[dict]] = defaultdict(list)
    for row in rows.values():
        if row.get("registro_produto") and _precos(row, alc=False):
            grupos[row["registro_produto"]].append(row)
    out = []
    for registro, lista in sorted(grupos.items()):
        lista.sort(key=lambda r: (r["apresentacao"] or "", r["ggrem"]))
        out.append(
            {
                "registro_produto": registro,
                "produto": _mais_comum([r["produto"] for r in lista]),
                "laboratorio": _mais_comum([r["laboratorio"] for r in lista]),
                "cnpj": _mais_comum([r["cnpj"] for r in lista]),
                "substancia": _mais_comum([r["substancia"] for r in lista]),
                "classe_terapeutica": _mais_comum([r["classe_terapeutica"] for r in lista]),
                "tipo_produto": _mais_comum([r["tipo_produto"] for r in lista]),
                "tarja": _mais_comum([r["tarja"] for r in lista]),
                "stamp": stamp,
                "publicado_em": publicado_em,
                "apresentacoes": [apresentacao(r) for r in lista],
            }
        )
    return out


def indice(lista: list[dict], *, stamp: str, publicado_em: str) -> dict:
    return {
        "stamp": stamp,
        "publicado_em": publicado_em,
        "produtos": [
            {
                "registro_produto": p["registro_produto"],
                "produto": p["produto"],
                "laboratorio": p["laboratorio"],
                "substancia": p["substancia"],
                "tipo_produto": p["tipo_produto"],
                "apresentacoes": len(p["apresentacoes"]),
                "comercializado": any(a["comercializado"] for a in p["apresentacoes"]),
            }
            for p in lista
        ],
    }


def _compact(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n"


def write_dados(out: Path, rows: dict[str, dict], *, stamp: str, publicado_em: str) -> int:
    """Write out/dados/{produtos.json, produto/<registro_produto>.json, schema.md}; returns the
    number of products."""
    lista = produtos(rows, stamp=stamp, publicado_em=publicado_em)
    pasta = Path(out) / "dados" / "produto"
    pasta.mkdir(parents=True, exist_ok=True)
    for p in lista:
        (pasta / f"{p['registro_produto']}.json").write_text(_compact(p), encoding="utf-8")
    (pasta.parent / "produtos.json").write_text(
        _compact(indice(lista, stamp=stamp, publicado_em=publicado_em)), encoding="utf-8"
    )
    (pasta.parent / "schema.md").write_text(SCHEMA.read_text(encoding="utf-8"), encoding="utf-8")
    return len(lista)
