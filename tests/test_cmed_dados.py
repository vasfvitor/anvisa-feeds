"""cmed/dados/: one JSON per product with the PMC at every ICMS rate, for the public portal."""

from __future__ import annotations

import json
from pathlib import Path

from test_cmed import dados, site_with_months  # noqa: F401  (dados is a fixture)

from anvisa_feeds import cmed, cmed_dados


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_products_hold_every_pharmacy_presentation(dados, client, tmp_path):  # noqa: F811
    snapshots, site, _ = site_with_months(dados, client, tmp_path, 1)
    rows = cmed.load_rows(snapshots / "cmed", "20261009")
    pasta = site / "cmed" / "dados"
    idx = read(pasta / "produtos.json")
    assert idx["stamp"] == "20261009" and idx["publicado_em"]

    com_pmc = {g: r for g, r in rows.items() if r["registro_produto"] and r["pmc_0"] is not None}
    sem_pmc = {g for g, r in rows.items() if r["pmc_0"] is None}
    assert sem_pmc, "the fixtures should include a hospital-only presentation"
    assert {p["registro_produto"] for p in idx["produtos"]} == {
        r["registro_produto"] for r in com_pmc.values()
    }

    vistos = set()
    for item in idx["produtos"]:
        p = read(pasta / "produto" / f"{item['registro_produto']}.json")
        assert p["produto"] == item["produto"] and len(p["apresentacoes"]) == item["apresentacoes"]
        for a in p["apresentacoes"]:
            row = rows[a["ggrem"]]
            vistos.add(a["ggrem"])
            assert a["pmc"]["0"] == row["pmc_0"]
            assert a["pmc"]["18"] == row["pmc_18"]
            assert a["pmc"]["17.5"] == row["pmc_17_5"]
            assert a["pmc_alc"].get("18") == row["pmc_18_alc"]
            assert "0" not in a["pmc_alc"]
            assert a["comercializado"] == (row["comercializacao"] == "S")
    assert vistos == set(com_pmc) and not (vistos & sem_pmc)
    assert (pasta / "schema.md").read_text(encoding="utf-8").startswith("# Preços máximos")


def test_todos_holds_the_same_products_as_the_files(dados, client, tmp_path):  # noqa: F811
    _, site, _ = site_with_months(dados, client, tmp_path, 1)
    pasta = site / "cmed" / "dados"
    idx = read(pasta / "produtos.json")
    todos = read(pasta / "todos.json")
    assert (todos["stamp"], todos["publicado_em"]) == (idx["stamp"], idx["publicado_em"])
    assert [p["registro_produto"] for p in todos["produtos"]] == [
        i["registro_produto"] for i in idx["produtos"]
    ]
    for p in todos["produtos"]:
        assert p == read(pasta / "produto" / f"{p['registro_produto']}.json")


def test_meta_contract_is_unchanged(dados, client, tmp_path):  # noqa: F811
    _, site, _ = site_with_months(dados, client, tmp_path, 1)
    bloco = read(site / "meta.json")["cmed"]
    assert "produtos" not in bloco and "pages" not in bloco


def test_rate_keys_follow_the_library():
    chaves = [k for k, _ in cmed_dados.ALIQUOTAS]
    assert chaves[:4] == ["0", "12", "17", "17.5"] and len(chaves) == 13
    row = {f"pmc_{s}": i for i, (_, s) in enumerate(cmed_dados.ALIQUOTAS)}
    row.update({f"pmc_{s}_alc": 100 + i for i, (_, s) in enumerate(cmed_dados.ALIQUOTAS)})
    assert cmed_dados._precos(row, alc=False)["17.5"] == 3
    assert cmed_dados._precos(row, alc=True)["17.5"] == 103
