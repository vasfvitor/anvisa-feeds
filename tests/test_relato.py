import html
import re
from datetime import date
from urllib.parse import parse_qs, quote, unquote, urlsplit

from test_cmed import dados, site_with_months  # noqa: F401  (dados is a fixture)

from anvisa_feeds.cmed_site import cnpj_fmt
from anvisa_feeds.crawl import crawl
from anvisa_feeds.feeds import (
    ASSUNTO_FEED,
    ASSUNTO_FEED_FILA,
    FEED_XSL_RELATO,
    RELATO_EMAIL,
    REPO_URL,
    build_site,
    q,
    relato,
    relato_links,
    relato_rodape,
    relato_urls,
)

PAGINA = "https://x.test/f/cmed/laboratorio/00000000000100.html"


def test_issue_url_prefills_the_form_with_every_value_encoded():
    item = "Água & Sal #2, ação\nlinha"
    issue, _ = relato_urls(PAGINA, item)
    parts = urlsplit(issue)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == f"{REPO_URL}/issues/new"
    assert parts.query == (
        "template=problema.yml"
        "&title=Problema%20em%20%C3%81gua%20%26%20Sal%20%232%2C%20a%C3%A7%C3%A3o%0Alinha"
        "&pagina=https%3A%2F%2Fx.test%2Ff%2Fcmed%2Flaboratorio%2F00000000000100.html"
        "&item=%C3%81gua%20%26%20Sal%20%232%2C%20a%C3%A7%C3%A3o%0Alinha"
    )
    assert parse_qs(parts.query) == {
        "template": ["problema.yml"],
        "title": [f"Problema em {item}"],
        "pagina": [PAGINA],
        "item": [item],
    }
    assert " " not in issue and "+" not in issue and "#" not in issue


def test_mailto_has_subject_and_body_with_spaces_as_percent_20_and_crlf_lines():
    _, mailto = relato_urls(PAGINA, "subfila 167 (Registro)")
    assert mailto.startswith(f"mailto:{RELATO_EMAIL}?subject=Problema%20em%20subfila%20167%20")
    assert "+" not in mailto and " " not in mailto
    query = mailto.split("?", 1)[1]
    fields = dict(p.split("=", 1) for p in query.split("&"))
    assert unquote(fields["subject"]) == "Problema em subfila 167 (Registro)"
    assert unquote(fields["body"]) == (
        f"Página: {PAGINA}\r\nItem: subfila 167 (Registro)\r\n\r\nO que está errado:\r\n\r\n"
        "O que a fonte oficial mostra (link):\r\n"
    )
    # RFC 6068: a line break in a mailto body is CRLF, never a bare LF
    assert fields["body"].count("%0A") == fields["body"].count("%0D%0A") == 6


def test_no_item_uses_the_page_title_and_leaves_item_empty():
    issue, mailto = relato_urls(PAGINA, titulo="Preços CMED")
    q = parse_qs(urlsplit(issue).query, keep_blank_values=True)
    assert q["title"] == ["Problema em Preços CMED"] and q["item"] == [""]
    assert q["pagina"] == [PAGINA]
    body = unquote(mailto.split("&body=", 1)[1])
    assert body.startswith(f"Página: {PAGINA}\r\nItem: \r\n\r\n")


def test_rendered_sentences_escape_the_ampersands_in_href():
    full = relato(PAGINA, "A & B")
    assert full.startswith('<p class="relato">Encontrou um erro? <a href="')
    assert "template=problema.yml&amp;title=" in full and "&title=" not in full
    assert ">Abra um relato no GitHub</a> (precisa de conta) ou <a href=" in full
    assert ">escreva para ajuda@abelhaninja.de</a>. O relato no GitHub é público: " in full
    assert full.endswith("não inclua dados pessoais.</p>")
    short = relato_rodape(PAGINA, "Filas")
    assert short.startswith('Encontrou um erro? <a href="')
    assert short.endswith(f'">{RELATO_EMAIL}</a>.')
    assert ">Relato no GitHub</a> (público: não inclua dados pessoais) ou <a href=" in short


def test_every_page_has_the_footer_and_item_pages_the_full_sentence(dados, client, tmp_path):  # noqa: F811
    _, site, _ = site_with_months(dados, client, tmp_path, 1)
    pages = list(site.rglob("*.html"))
    assert len(pages) > 30
    for path in pages:
        text = path.read_text(encoding="utf-8")
        footer = text[text.index("<footer>") :]
        assert ">Relato no GitHub</a> (público: não inclua dados pessoais) ou " in footer, path
        canonical = re.search(r'<link rel="canonical" href="([^"]*)"', text)[1]
        (href,) = re.findall(r'<a href="([^"]*)">Relato no GitHub', footer)
        q = parse_qs(urlsplit(html.unescape(href)).query, keep_blank_values=True)
        # the 404 is served at any missing path: the reader fills the page in
        pagina = "" if path.name == "404.html" else html.unescape(canonical)
        assert q["pagina"] == [pagina] and q["item"] == [""], path
        item_page = path.parent.name in ("fila", "substancia", "laboratorio")
        assert ('<p class="relato">' in text) == item_page, path
        if item_page:  # after the data, inside main
            assert text.index('<p class="relato">') < text.index("</main>")

    def item(path):
        text = path.read_text(encoding="utf-8")
        (href,) = re.findall(r'<a href="([^"]*)">Abra um relato no GitHub', text)
        return parse_qs(urlsplit(html.unescape(href)).query)["item"][0]

    assert re.fullmatch(r"subfila 167 \(.+\)", item(site / "fila" / "167.html"))
    lab = next((site / "cmed" / "laboratorio").glob("*.html"))
    assert re.fullmatch(r".+ \(CNPJ \d\d\.\d{3}\.\d{3}/\d{4}-\d\d\)", item(lab))
    issue = re.search(r'<a href="([^"]*)">Abra um relato no GitHub', lab.read_text())[1]
    title = parse_qs(urlsplit(html.unescape(issue)).query)["title"][0]
    assert title == f"Problema em {item(lab)}"
    subst = next((site / "cmed" / "substancia").glob("*.html"))
    assert item(subst) and "CNPJ" not in item(subst)


def test_cnpj_is_written_with_its_mask():
    assert cnpj_fmt("00029372000140") == "00.029.372/0001-40"
    assert cnpj_fmt("12ABC34501DE35") == "12.ABC.345/01DE-35"  # alphanumeric CNPJ, same mask
    assert cnpj_fmt("00.029.372/0001-40") == "00.029.372/0001-40"
    assert cnpj_fmt("123") == "123"
    assert cnpj_fmt(" 123 ") == "123"  # stripped on both paths
    assert cnpj_fmt(" 00029372000140 ") == "00.029.372/0001-40"


def test_the_404_footer_leaves_the_page_for_the_reader(client, tmp_path):
    snapshots, site = tmp_path / "snapshots", tmp_path / "site"
    crawl(client, snapshots, day=date(2026, 9, 6), areas=[8], log=lambda s: None)
    build_site(snapshots, site, base_url="https://x.test/f", base_tag="x.test,2026:f")
    footer = (site / "404.html").read_text(encoding="utf-8").split("<footer>")[1]
    issue, mailto = re.findall(r'<a href="([^"]*)">', footer)
    q = parse_qs(urlsplit(html.unescape(issue)).query, keep_blank_values=True)
    assert q["pagina"] == [""] and q["item"] == [""]
    assert q["title"] == ["Problema em Página não encontrada"]
    assert "&amp;body=P%C3%A1gina%3A%20%0D%0AItem%3A%20%0D%0A" in mailto


def test_laboratorio_pages_show_the_cnpj_masked_and_a_nameless_one_is_named_by_it(
    dados,  # noqa: F811
    client,
    tmp_path,
):
    def add_nameless(kind, rows):
        h = rows[0]
        new = list(rows[1])
        new[h.index("CÓDIGO GGREM")] = "999999999999998"
        new[h.index("CNPJ")], new[h.index("LABORATÓRIO")] = "00.029.372/0001-40", ""
        rows.append(new)

    dados.next_month(add_nameless)
    _, site, _ = site_with_months(dados, client, tmp_path, 1)
    labs = site / "cmed" / "laboratorio"
    bayer = (labs / "18459628000115.html").read_text(encoding="utf-8")
    assert "<span>CNPJ 18.459.628/0001-15</span>" in bayer and "CNPJ 18459628000115" not in bayer
    page = (labs / "00029372000140.html").read_text(encoding="utf-8")
    (href,) = re.findall(r'<a href="([^"]*)">Abra um relato no GitHub', page)
    assert parse_qs(urlsplit(html.unescape(href)).query)["item"] == ["CNPJ 00.029.372/0001-40"]
    assert "<h1>CNPJ 00.029.372/0001-40</h1>" in page.replace("<wbr>", "")
    assert "00029372000140 (" not in page
    index = (site / "cmed" / "index.html").read_text(encoding="utf-8")
    assert '00029372000140.html">CNPJ 00.029.372/0001-40</a>' in index


# what feed.xsl's `troca` template does to the self URL; the only escapes it knows
def troca_xsl(url: str) -> str:
    return url.replace(":", "%3A").replace("/", "%2F")


def test_every_feed_self_url_needs_only_the_escapes_the_xsl_makes(dados, client, tmp_path):  # noqa: F811
    """XSLT 1.0 cannot percent-encode: feed.xsl escapes ":" and "/" of the feed's self URL and
    nothing else, so every self URL must hold no other character a query would escape."""
    _, site, _ = site_with_months(dados, client, tmp_path, 2)
    feeds = [f for f in site.rglob("*.xml") if "<feed" in f.read_text(encoding="utf-8")]
    assert {f.parent.name for f in feeds} >= {"fila", "substancia", "laboratorio", "cmed"}
    for f in feeds:
        self_url = re.search(r'<link rel="self" href="([^"]+)"', f.read_text(encoding="utf-8"))[1]
        assert re.fullmatch(r"[A-Za-z0-9._~:/-]+", self_url), f
        assert troca_xsl(self_url) == quote(self_url, safe=""), f


def test_the_feed_views_footer_matches_the_python_links(dados, client, tmp_path):  # noqa: F811
    """feed.xsl (fila and CMED) carries the footer; with its variables filled as the XSLT fills
    them, the hrefs are the ones relato_links builds."""
    _, site, _ = site_with_months(dados, client, tmp_path, 1)
    for xsl in (site / "feed.xsl", site / "cmed" / "feed.xsl"):
        text = xsl.read_text(encoding="utf-8")
        assert FEED_XSL_RELATO in text and '<xsl:template name="troca">' in text, xsl
    assert "(público: não inclua dados pessoais)" in FEED_XSL_RELATO
    for self_url, assunto in [
        ("https://x.test/f/fila/167.xml", ASSUNTO_FEED_FILA),
        ("https://x.test/f/cmed/laboratorio/18459628000115.xml", ASSUNTO_FEED),
        ("https://x.test/f/cmed/geral.xml", ASSUNTO_FEED),
    ]:
        assert ("/fila/" in self_url) == (assunto == ASSUNTO_FEED_FILA)
        rodape = FEED_XSL_RELATO.replace("{$pagina}", troca_xsl(self_url)).replace(
            "{$assunto}", quote(assunto, safe="")
        )
        issue, mailto = relato_links(self_url, "", assunto)
        assert f'href="{q(issue)}"' in rodape
        assert f'href="{q(mailto)}"' in rodape
