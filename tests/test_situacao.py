"""Registration status and ANVISA measures from the anvisa-api Parquet, joined to cmed/dados."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import httpx

from anvisa_feeds import cmed_dados, situacao


def tables(tmp: Path) -> dict[str, Path]:
    """The two tables with the columns the module reads, shaped like the 2026-10-28 build."""
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    mpp, med = tmp / "mpp.parquet", tmp / "medidas.parquet"
    con.execute(
        f"""COPY (SELECT * FROM (VALUES
              ('116180267', true, DATE '2028-06-01'),
              ('103110182', false, DATE '2021-01-01'),
              (NULL, true, NULL)
            ) t(registro_produto, ativo, vencimento)) TO '{mpp}' (FORMAT parquet)"""
    )
    con.execute(
        f"""COPY (SELECT * FROM (VALUES
              (1, 1, '25351104206202604', ['103110182'], ['Recolhimento', 'Suspensão'],
               ['Comercialização', 'Uso'], DATE '2026-10-06'),
              (2, 1, '25351000000202600', ['103110182'], ['Proibição'], ['Propaganda'],
               DATE '2025-01-02'),
              (3, 2, '25351999999202699', ['116180267'], ['Proibição'], ['Uso'],
               DATE '2026-01-01'),
              (4, 1, '25351888888202688', ['999999999'], ['Proibição'], ['Uso'],
               DATE '2026-01-01')
            ) t(dossie, area_codigo, processo, registros, acoes, atividades, ultima))
            TO '{med}' (FORMAT parquet)"""
    )
    return {"medicamentos_por_produto": mpp, "medidas": med}


def test_load_joins_by_registro_and_keeps_only_medicine_measures(tmp_path):
    s = situacao.load(tables(tmp_path))
    assert s["116180267"] == {"ativo": True, "vencimento": "2028-06", "medidas": []}  # area 2
    lizbi = s["103110182"]
    assert lizbi["ativo"] is False and lizbi["vencimento"] == "2021-01"
    assert [m["data"] for m in lizbi["medidas"]] == ["2026-10-06", "2025-01-02"]  # newest first
    assert lizbi["medidas"][0] == {
        "data": "2026-10-06",
        "acoes": ["Recolhimento", "Suspensão"],
        "atividades": ["Comercialização", "Uso"],
        "processo": "25351104206202604",
    }
    assert "999999999" not in s and None not in s


def test_fetch_reads_the_paths_from_the_manifest(tmp_path):
    files = tables(tmp_path / "src")
    # the shape of the live manifest: tables keyed by name
    manifest = {
        "build_id": "b1",
        "built_at": "2026-10-28T00:08:51Z",
        "tables": {n: {"path": f"data/b1/{n}.parquet"} for n in situacao.TABLES},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("manifest.json"):
            return httpx.Response(200, json=manifest)
        name = path.rsplit("/", 1)[1].removesuffix(".parquet")
        return httpx.Response(200, content=files[name].read_bytes())

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        got, fonte = situacao.fetch(
            tmp_path / "cache", manifest_url="https://x.test/a/manifest.json", http=http
        )
    assert set(got) == set(situacao.TABLES)
    assert fonte == {"build_id": "b1", "built_at": "2026-10-28T00:08:51Z"}
    assert situacao.load(got)["103110182"]["ativo"] is False


def test_carregar_gives_none_when_the_source_fails(tmp_path):
    lines = []
    assert (
        situacao.carregar(tmp_path, manifest_url="http://127.0.0.1:9/m.json", log=lines.append)
        is None
    )
    assert lines and "indisponível" in lines[0]


def test_products_carry_status_and_measures_only_when_the_source_was_read():
    row = {
        "ggrem": "1",
        "registro_produto": "103110182",
        "apresentacao": "x",
        "regime_preco": "Regulado",
        "comercializacao": "S",
        "comercializacao_periodo": "2025",
        "restricao_hospitalar": "N",
        "icms_0": "N",
        "pmc_0": 100,
        "tipo_produto": "Novo",
        "tarja": None,
    }
    for k in ("produto", "laboratorio", "cnpj", "substancia", "classe_terapeutica"):
        row[k] = "x"
    medida = {"data": "2026-10-06", "acoes": ["Recolhimento"], "atividades": [], "processo": "1"}
    s = {"103110182": {"ativo": False, "vencimento": "2021-01", "medidas": [medida]}}
    (p,) = cmed_dados.produtos({"1": row}, stamp="s", publicado_em="p", situacao=s)
    assert p["situacao"] == {"ativo": False, "vencimento": "2021-01"}
    assert p["medidas"] == [medida]
    (sem_registro,) = cmed_dados.produtos({"1": row}, stamp="s", publicado_em="p", situacao={})
    assert sem_registro["situacao"] is None and sem_registro["medidas"] == []
    (fonte_fora,) = cmed_dados.produtos({"1": row}, stamp="s", publicado_em="p")
    assert "situacao" not in fonte_fora and "medidas" not in fonte_fora
    json.dumps(p)  # what write_dados writes


def test_index_files_say_whether_the_registration_source_was_read(tmp_path):
    # a source that could not be read is null at the top of both files, not just missing keys:
    # the portal and the workflow tell it apart from a day with nothing to report
    row = {
        "ggrem": "1",
        "registro_produto": "103110182",
        "apresentacao": "x",
        "regime_preco": "Regulado",
        "comercializacao": "S",
        "comercializacao_periodo": "2025",
        "restricao_hospitalar": "N",
        "icms_0": "N",
        "pmc_0": 100,
        "tipo_produto": "Novo",
        "tarja": None,
    }
    for k in ("produto", "laboratorio", "cnpj", "substancia", "classe_terapeutica"):
        row[k] = "x"
    fonte = {"build_id": "b1", "built_at": "2026-10-28T00:08:51Z"}
    lida = situacao.Situacao(fonte=fonte, registros={})
    for s, esperado in ((lida, fonte), (None, None)):
        out = tmp_path / str(esperado is None)
        cmed_dados.write_dados(out, {"1": row}, stamp="s", publicado_em="p", situacao=s)
        for nome in ("produtos.json", "todos.json"):
            dados = json.loads((out / "dados" / nome).read_text(encoding="utf-8"))
            assert dados["situacao_fonte"] == esperado, nome
