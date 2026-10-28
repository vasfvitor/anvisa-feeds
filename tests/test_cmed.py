"""The CMED side: monthly crawl (two conditional GETs), the keyed diff, and the cmed/ pages
built beside the fila ones. The fixtures are the 22-record samples of the anvisa-api repo."""

from __future__ import annotations

import csv
import io
import json
import lzma
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

import httpx
import pytest
from anvisa.dados import cmed as reader
from anvisa.dados.fetch import http_client

from anvisa_feeds import cmed, cmed_site
from anvisa_feeds.crawl import crawl as crawl_filas
from anvisa_feeds.diff import diff_keyed, summary_keyed
from anvisa_feeds.feeds import build_site

ATOM = "{http://www.w3.org/2005/Atom}"
FIXTURES = Path(__file__).parent / "fixtures" / "cmed"
ETAGS = {"pmc": '"105a8a6-65d6a342ad836"', "pmvg": '"10fc04a-65d6a358b7d85"'}
MODIFIED = {"pmc": "Fri, 09 Oct 2026 15:43:03 GMT", "pmvg": "Fri, 09 Oct 2026 15:43:26 GMT"}


class FakeDados:
    """Serves the two files with ETag and Last-Modified, honouring If-None-Match."""

    def __init__(self) -> None:
        self.files = {k: (FIXTURES / f).read_bytes() for k, f in reader.FILES.items()}
        self.etags = dict(ETAGS)
        self.modified = dict(MODIFIED)
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        kind = next((k for k, f in reader.FILES.items() if str(request.url).endswith(f)), None)
        if kind is None:
            return httpx.Response(404)
        headers = {"ETag": self.etags[kind], "Last-Modified": self.modified[kind]}
        if request.headers.get("If-None-Match") == self.etags[kind]:
            return httpx.Response(304, headers=headers)
        return httpx.Response(200, headers=headers, content=self.files[kind])

    def client(self) -> httpx.Client:
        return http_client(transport=httpx.MockTransport(self.handler))

    def next_month(self, edit) -> None:
        """A new cut: `edit(rows)` changes the parsed PMC rows in place (list of lists, header
        first); the PMVG file gets the same GGREM set with its own prices."""
        for kind in reader.KINDS:
            text = self.files[kind].decode("utf-8-sig")
            rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))
            edit(kind, rows)
            buf = io.StringIO(newline="")
            csv.writer(buf, delimiter=";", lineterminator="\r\n").writerows(rows)
            self.files[kind] = ("﻿" + buf.getvalue()).encode("utf-8")
            self.etags[kind] = f'"{kind}-nov"'
            self.modified[kind] = "Mon, 09 Nov 2026 15:00:00 GMT"


@pytest.fixture
def dados() -> FakeDados:
    return FakeDados()


def snapshot_month(dados: FakeDados, out: Path, raw: Path) -> dict | None:
    with dados.client() as http:
        return cmed.crawl(out, raw_dir=raw, http=http, log=lambda s: None)


def test_crawl_writes_a_month_and_skips_when_unchanged(dados, tmp_path):
    out, raw = tmp_path / "cmed", tmp_path / "raw"
    meta = snapshot_month(dados, out, raw)
    assert meta and meta["stamp"] == "20261009" and meta["rows"] == 23
    assert meta["publicado_em"] == "09/10/2026 12:43:03"
    assert meta["only_pmc"] == 1 and meta["only_pmvg"] == 1
    assert [f["etag"] for f in meta["files"]] == [ETAGS["pmc"], ETAGS["pmvg"]]
    assert meta["release"] == "cmed-20261009"
    assert cmed.stamps(out) == ["20261009"] and cmed.load_meta(out, "20261009") == meta
    assert (raw / "TA_PRECO_MEDICAMENTO.csv").read_bytes() == dados.files["pmc"]
    rows = cmed.load_rows(out, "20261009")
    assert len(rows) == 23 and rows["538912020009303"]["pf_0"] == 3073
    assert rows["538912020009303"]["pmvg_0"] == 2465 and rows["538912020009303"]["cap"] == "N"
    with lzma.open(out / "20261009.jsonl.xz", "rt", encoding="utf-8") as fh:
        first = json.loads(next(fh))
    assert first == {"columns": list(reader.COLUMNS)}

    dados.requests.clear()
    assert snapshot_month(dados, out, raw) is None  # both 304
    sent = [r.headers.get("If-None-Match") for r in dados.requests]
    assert sent == [ETAGS["pmc"], ETAGS["pmvg"]]
    assert cmed.stamps(out) == ["20261009"]


def test_crawl_refetches_the_pair_when_one_file_changed(dados, tmp_path):
    out, raw = tmp_path / "cmed", tmp_path / "raw"
    snapshot_month(dados, out, raw)
    dados.etags["pmvg"], dados.modified["pmvg"] = '"x"', "Mon, 09 Nov 2026 15:00:00 GMT"
    dados.requests.clear()
    meta = snapshot_month(dados, out, raw)
    assert meta and meta["stamp"] == "20261009"  # the stamp is the PMC file's day
    urls = [str(r.url).rsplit("/", 1)[1] for r in dados.requests]
    assert urls == [reader.FILES["pmc"], reader.FILES["pmvg"], reader.FILES["pmc"]]


def test_crawl_refuses_a_month_that_lost_many_rows(dados, tmp_path):
    out, raw = tmp_path / "cmed", tmp_path / "raw"
    snapshot_month(dados, out, raw)

    def drop_three(kind, rows):
        del rows[1:4]  # 23 → 20 rows: under 95 % of the previous month

    dados.next_month(drop_three)
    with pytest.raises(SystemExit, match="20 rows against 23"):
        snapshot_month(dados, out, raw)
    assert cmed.stamps(out) == ["20261009"]  # nothing written
    with dados.client() as http:  # a list that really shrank goes in with a lower ratio
        meta = cmed.crawl(out, raw_dir=raw, http=http, log=lambda s: None, min_rows_ratio=0.5)
    assert meta and meta["stamp"] == "20261109" and meta["rows"] == 20


def test_the_comercializacao_year_rolling_over_is_not_a_change():
    a = {"g1": {"pf_0": 100, "comercializacao": "S", "comercializacao_periodo": "2025"}}
    b = {"g1": {"pf_0": 100, "comercializacao": "S", "comercializacao_periodo": "2026"}}
    assert diff_keyed(a, b, cmed_site.FIELDS) == []


def test_change_li_labels_fields_and_never_says_descontinuado():
    row = {"produto": "X", "apresentacao": "1 CP", "comercializacao_periodo": "2025"}
    li = cmed_site.change_li(
        {
            "type": "changed",
            "row": row,
            "changes": {"comercializacao": ["S", "N"], "regime_preco": ["Regulado", "Liberado"]},
        }
    )
    assert "sem comercialização informada em 2025" in li
    assert "regime de preço: Regulado → Liberado" in li
    assert "descontinu" not in li and "comercializacao" not in li


def test_diff_keyed_reports_entered_left_and_field_changes():
    a = {"g1": {"pf_0": 100, "tarja": "x"}, "g2": {"pf_0": 5, "tarja": "y"}, "g3": {"pf_0": 1}}
    b = {"g1": {"pf_0": 110, "tarja": "x"}, "g2": {"pf_0": 5, "tarja": "y"}, "g4": {"pf_0": 2}}
    events = diff_keyed(a, b, ("pf_0", "tarja"))
    assert [(e["type"], e["key"]) for e in events] == [
        ("changed", "g1"),
        ("left", "g3"),
        ("entered", "g4"),
    ]
    assert events[0]["changes"] == {"pf_0": [100, 110]} and events[0]["old"] == a["g1"]
    assert events[1]["row"] == a["g3"] and events[2]["old"] is None
    assert summary_keyed(events) == "1 entrou, 1 mudou, 1 saiu"
    assert summary_keyed([]) == "sem mudanças"
    # a field not listed does not count as a change
    assert diff_keyed(a, {**a, "g1": {"pf_0": 100, "tarja": "z"}}, ("pf_0",)) == []


def site_with_months(dados, client, tmp_path, months: int) -> tuple[Path, Path, dict]:
    """Fila snapshots for two days plus `months` CMED snapshots (the second month edits the
    PMC prices of two GGREMs, drops one and adds one), built into tmp_path/site."""
    snapshots, site = tmp_path / "snapshots", tmp_path / "site"
    crawl_filas(client, snapshots, day=date(2026, 9, 6), areas=[8], log=lambda s: None)
    out, raw = snapshots / "cmed", tmp_path / "raw"
    snapshot_month(dados, out, raw)
    if months > 1:

        def edit(kind, rows):
            h = rows[0]
            g, pf0, pmc0, tarja = (
                h.index("CÓDIGO GGREM"),
                h.index("PF 0%"),
                h.index("PMC 0 %") if "PMC 0 %" in h else None,
                h.index("TARJA"),
            )
            for r in rows[1:]:
                if r[g] == "538912020009303":  # BAYCUTEN: +10 % on PF 0 %, tarja changed
                    r[pf0] = "33,80"
                    r[tarja] = "Tarja Vermelha"
                if r[g] == "508011303163310" and pmc0 is not None:  # PROFLAM: PMC down
                    r[pmc0] = "40,00"
            rows[:] = [r for r in rows if r[g] != "526520120096607"]  # ZOLGENSMA leaves
            new = list(rows[1])
            new[g], new[h.index("SUBSTÂNCIA")] = "999999999999999", "NOVA SUBSTANCIA"
            new[h.index("PRODUTO")] = "NOVO"
            new[h.index("CNPJ")], new[h.index("LABORATÓRIO")] = "00.000.000/0001-91", "NOVO LAB"
            rows.append(new)

        dados.next_month(edit)
        snapshot_month(dados, out, raw)
    result = build_site(
        snapshots, site, base_url="https://x.test/f", base_tag="x.test,2026:f", cmed_months=12
    )
    return snapshots, site, result


def test_build_without_cmed_snapshots_is_the_fila_site(client, tmp_path):
    snapshots, site = tmp_path / "snapshots", tmp_path / "site"
    crawl_filas(client, snapshots, day=date(2026, 9, 6), areas=[8], log=lambda s: None)
    result = build_site(snapshots, site, base_url="https://x.test/f", base_tag="x.test,2026:f")
    assert "cmed" not in result and not (site / "cmed").exists()
    meta = json.loads((site / "meta.json").read_text(encoding="utf-8"))
    assert "cmed" not in meta
    assert "cmed/index.html" not in (site / "index.html").read_text(encoding="utf-8")


def test_first_month_builds_feeds_without_a_diff(dados, client, tmp_path):
    _, site, result = site_with_months(dados, client, tmp_path, 1)
    assert result["cmed"] == {"stamp": "20261009", "feeds": 1 + 20 + 16, "months": 1}
    cmed_dir = site / "cmed"
    for f in ("index.html", "geral.xml", "cmed.opml", "feed.xsl"):
        assert (cmed_dir / f).exists()
    subst = ET.parse(cmed_dir / "substancia" / "acebrofilina.xml").getroot()
    assert subst.find(f"{ATOM}id").text == "tag:x.test,2026:f:cmed/substancia/acebrofilina"
    entries = subst.findall(f"{ATOM}entry")
    assert len(entries) == 1
    assert entries[0].find(f"{ATOM}title").text == "Lista de 09/10/2026: sem mudanças"
    assert entries[0].find(f"{ATOM}id").text.endswith("/acebrofilina/20261009")
    content = entries[0].find(f"{ATOM}content").text
    assert "Lista atual (2 apresentações)" in content and "ACEBROFILINA" in content
    raw = (cmed_dir / "substancia" / "acebrofilina.xml").read_bytes()
    assert b'href="../feed.xsl"' in raw and b"dados: CMED/ANVISA" in raw
    assert b'href="feed.xsl"' in (cmed_dir / "geral.xml").read_bytes()
    lab = ET.parse(cmed_dir / "laboratorio" / "18459628000115.xml").getroot()
    assert lab.find(f"{ATOM}title").text == "Preços CMED: BAYER S.A."
    page = (cmed_dir / "substancia" / "acebrofilina.html").read_text(encoding="utf-8")
    head = page.split("<body>")[0]
    assert (
        '<link rel="canonical" href="https://x.test/f/cmed/substancia/acebrofilina.html">' in head
    )
    assert 'href="https://x.test/f/cmed/substancia/acebrofilina.xml">' in head
    assert "Preços CMED</a>" in page and "Todas as filas</a>" in page
    assert "dados.anvisa.gov.br" in page and "API Consultas Externas" not in page
    data = json.loads((cmed_dir / "substancia" / "acebrofilina.json").read_text(encoding="utf-8"))
    assert data["substancia"] == "ACEBROFILINA" and data["lista"] == "20261009"
    assert list(data["apresentacoes"][0]) == list(cmed_site.JSON_FIELDS)
    assert data["mudancas"] == []
    index = (cmed_dir / "index.html").read_text(encoding="utf-8")
    assert "a primeira lista guardada" in index and "releases/tag/cmed-20261009" in index
    assert index.count('<a class="feed"') == 20 + 16
    opml = ET.parse(cmed_dir / "cmed.opml").getroot()
    assert len(opml.findall(".//outline[@type='rss']")) == 1 + 20 + 16
    sm = ET.parse(site / "sitemap.xml").getroot()
    locs = [u[0].text for u in sm]
    assert "https://x.test/f/cmed/" in locs and locs.count("https://x.test/f/") == 1
    assert sum(1 for loc in locs if "/cmed/" in loc) == 1 + 20 + 16
    meta = json.loads((site / "meta.json").read_text(encoding="utf-8"))
    assert meta["cmed"]["rows"] == 23 and meta["cmed"]["substancias"] == 20
    assert meta["cmed"]["laboratorios"] == 16 and meta["cmed"]["feeds"] == 1 + 20 + 16
    assert meta["cmed"]["events"] == {"entered": 0, "changed": 0, "left": 0}
    assert meta["feeds"] == result["feeds"]  # the fila count is untouched
    home = (site / "index.html").read_text(encoding="utf-8")
    assert 'href="cmed/index.html"' in home


def test_second_month_diffs_and_groups(dados, client, tmp_path):
    snapshots, site, result = site_with_months(dados, client, tmp_path, 2)
    assert cmed.stamps(snapshots / "cmed") == ["20261009", "20261109"]
    assert result["cmed"]["months"] == 2 and result["cmed"]["stamp"] == "20261109"
    cmed_dir = site / "cmed"
    meta = json.loads((site / "meta.json").read_text(encoding="utf-8"))["cmed"]
    assert meta["events"] == {"entered": 1, "changed": 2, "left": 1}
    bayer = ET.parse(cmed_dir / "laboratorio" / "18459628000115.xml").getroot()
    entries = bayer.findall(f"{ATOM}entry")
    # like the filas: the first list has no diff, so the feed carries one entry per later list
    assert [e.find(f"{ATOM}title").text for e in entries] == ["Lista de 09/11/2026: 1 mudou"]
    content = entries[0].find(f"{ATOM}content").text
    assert "BAYCUTEN N" in content and "R$ 30,73 → R$ 33,80 +10,0 %" in content
    assert "tarja: - (*) → Tarja Vermelha" in content
    assert "Lista atual (3 apresentações)" in content
    page = (cmed_dir / "laboratorio" / "18459628000115.html").read_text(encoding="utf-8")
    assert "Listas anteriores" not in page  # nothing before the first diff
    general = ET.parse(cmed_dir / "geral.xml").getroot()
    newest = general.findall(f"{ATOM}entry")[0]
    assert newest.find(f"{ATOM}title").text == "Lista de 09/11/2026: 1 entrou, 2 mudaram, 1 saiu"
    assert "ZOLGENSMA" in newest.find(f"{ATOM}content").text
    d = meta["destaques"]
    assert d["altas"][0]["produto"] == "BAYCUTEN N" and d["altas"][0]["variacao"] == 10.0
    assert d["altas"][0]["pf_de"] == 3073 and d["altas"][0]["pf_para"] == 3380
    assert d["altas"][0]["pagina"].endswith(
        "/cmed/substancia/21-acetato-de-dexametasona-clotrimazol.html"
    )
    assert [x["produto"] for x in d["entradas"]] == ["NOVO"]
    assert [x["produto"] for x in d["saidas"]] == ["ZOLGENSMA"] and d["saidas"][0][
        "pf_para"
    ] is None
    index = (cmed_dir / "index.html").read_text(encoding="utf-8")
    assert "Maiores altas de PF" in index and "BAYCUTEN N" in index
    assert "NOVO" in index and "ZOLGENSMA" in index
    # the new substância has a page and the one that left keeps a page saying so
    assert (cmed_dir / "substancia" / "nova-substancia.html").exists()
    page = (cmed_dir / "substancia" / "onasemnogeno-abeparvoveque.html").read_text(encoding="utf-8")
    assert "saiu da lista" in page
    data = json.loads(
        (cmed_dir / "substancia" / "nova-substancia.json").read_text(encoding="utf-8")
    )
    assert data["mudancas"][0]["type"] == "entered" and "old" not in data["mudancas"][0]


def test_long_substancia_names_get_short_stable_slugs():
    name = "A" * 300
    slugs = cmed_site.unique_slugs([name, "B"])
    assert len(slugs[name]) <= cmed_site.SLUG_MAX and slugs["B"] == "b"
    assert slugs == cmed_site.unique_slugs(["B", name])  # order of input does not matter
    both = cmed_site.unique_slugs(["Ácido X", "Acido X"])
    assert sorted(both.values()) == ["acido-x", "acido-x-2"]
