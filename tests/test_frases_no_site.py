"""The phrases of frases-proibidas.txt stay out of the built site, not only out of the source
strings: a sentence put together at build time (a count, a date, a notice) is checked as the reader
gets it. The list and its matcher are test_frases_proibidas.py's (shared byte for byte with ans, so
this check lives in its own file).

Read per file: the text of every .html page (style sheets and scripts out, JSON-LD in), the
description, title, placeholder and aria-label attributes, and every text and attribute of the
Atom feeds, the OPML files and the XSL style sheets, with the entries' HTML content unescaped.
"""

import html
import re
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

from test_cmed import dados, site_with_months  # noqa: F401  (dados is a fixture)
from test_feeds import next_day
from test_frases_proibidas import achados

from anvisa_feeds.crawl import crawl
from anvisa_feeds.feeds import build_site

CODE = re.compile(
    r"<style>.*?</style>|<script>.*?</script>|<script(?![^>]*ld\+json)[^>]*>.*?</script>", re.S
)
ATTRS = re.compile(r'\b(?:content|title|placeholder|aria-label)="([^"]*)"')


def texto_html(fonte: str) -> str:
    sem_codigo = CODE.sub(" ", fonte)
    atributos = " ".join(html.unescape(m) for m in ATTRS.findall(sem_codigo))
    return html.unescape(sem_codigo) + " " + atributos


def texto_xml(fonte: bytes) -> str:
    partes = []
    for el in ET.fromstring(fonte).iter():
        partes += [el.text or "", *el.attrib.values(), el.tail or ""]
    return " ".join(partes)  # an entry's HTML content comes back unescaped; achados drops tags


def achados_no_site(site: Path) -> list[str]:
    hits = []
    for path in sorted(site.rglob("*")):
        if path.suffix == ".html":
            texto = texto_html(path.read_text(encoding="utf-8"))
        elif path.suffix in (".xml", ".opml", ".xsl"):
            texto = texto_xml(path.read_bytes())
        else:
            continue
        hits += achados(str(path.relative_to(site)), [[(1, texto)]])
    return hits


def test_no_banned_phrase_in_the_built_site(dados, client, tmp_path):  # noqa: F811
    # two CMED lists (a diff, entries, exits, highlights) and fila collections with a diff on
    # consecutive days and one across a missed day
    snapshots, site, _ = site_with_months(dados, client, tmp_path, 2)
    next_day(snapshots, date(2026, 9, 6), date(2026, 9, 7))
    next_day(snapshots, date(2026, 9, 7), date(2026, 9, 9))
    build_site(snapshots, site, base_url="https://x.test/f", base_tag="x.test,2026:f")
    assert (site / "cmed" / "index.html").exists() and (site / "fila" / "167.html").exists()
    assert len(list(site.rglob("*.html"))) > 50
    hits = achados_no_site(site)
    assert not hits, "\n".join(hits)


def test_the_check_reads_built_text_and_attributes(client, tmp_path):
    # a phrase that only exists once the build runs (the notice) is found on the pages, and so is
    # one in an attribute
    snapshots, site = tmp_path / "snapshots", tmp_path / "site"
    crawl(client, snapshots, day=date(2026, 9, 6), areas=[8], log=lambda s: None)
    build_site(
        snapshots,
        site,
        base_url="https://x.test/f",
        base_tag="x.test,2026:f",
        notice="Saiba <b>mais</b> em tempo real",
    )
    hits = achados_no_site(site)
    assert "index.html:1: saiba mais" in hits and "fila/167.html:1: em tempo real" in hits
    meta = texto_html('<meta name="description" content="Clique aqui"><a title="só fatos">x</a>')
    assert achados("x", [[(1, meta)]]) == ["x:1: clique aqui", "x:1: só fatos"]
