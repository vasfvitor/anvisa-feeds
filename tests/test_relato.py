import html
import re
from datetime import date
from urllib.parse import parse_qs, unquote, urlsplit

from test_cmed import dados, site_with_months  # noqa: F401  (dados is a fixture)

from anvisa_feeds.cmed_site import cnpj_fmt
from anvisa_feeds.crawl import crawl
from anvisa_feeds.feeds import (
    RELATO_EMAIL,
    REPO_URL,
    build_site,
    relato,
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


def test_mailto_has_subject_and_body_with_spaces_as_percent_20():
    _, mailto = relato_urls(PAGINA, "subfila 167 (Registro)")
    assert mailto.startswith(f"mailto:{RELATO_EMAIL}?subject=Problema%20em%20subfila%20167%20")
    assert "+" not in mailto and " " not in mailto
    query = mailto.split("?", 1)[1]
    fields = dict(p.split("=", 1) for p in query.split("&"))
    assert unquote(fields["subject"]) == "Problema em subfila 167 (Registro)"
    assert unquote(fields["body"]) == (
        f"Página: {PAGINA}\nItem: subfila 167 (Registro)\n\nO que está errado:\n\n"
        "O que a fonte oficial mostra (link):\n"
    )


def test_no_item_uses_the_page_title_and_leaves_item_empty():
    issue, mailto = relato_urls(PAGINA, titulo="Preços CMED")
    q = parse_qs(urlsplit(issue).query, keep_blank_values=True)
    assert q["title"] == ["Problema em Preços CMED"] and q["item"] == [""]
    assert q["pagina"] == [PAGINA]
    body = unquote(mailto.split("&body=", 1)[1])
    assert body.startswith(f"Página: {PAGINA}\nItem: \n\n")


def test_rendered_sentences_escape_the_ampersands_in_href():
    full = relato(PAGINA, "A & B")
    assert full.startswith('<p class="relato">Encontrou um erro? <a href="')
    assert "template=problema.yml&amp;title=" in full and "&title=" not in full
    assert ">Abra um relato no GitHub</a> (precisa de conta) ou <a href=" in full
    assert ">escreva para ajuda@abelhaninja.de</a>. O relato no GitHub é público: " in full
    assert full.endswith("não inclua dados pessoais.</p>")
    short = relato_rodape(PAGINA, "Filas")
    assert short.startswith('Encontrou um erro? <a href="')
    assert short.endswith(f'">{RELATO_EMAIL}</a>.') and ">Relato no GitHub</a> ou " in short


def test_every_page_has_the_footer_and_item_pages_the_full_sentence(dados, client, tmp_path):  # noqa: F811
    _, site, _ = site_with_months(dados, client, tmp_path, 1)
    pages = list(site.rglob("*.html"))
    assert len(pages) > 30
    for path in pages:
        text = path.read_text(encoding="utf-8")
        footer = text[text.index("<footer>") :]
        assert ">Relato no GitHub</a> ou " in footer, path
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


def test_the_404_footer_leaves_the_page_for_the_reader(client, tmp_path):
    snapshots, site = tmp_path / "snapshots", tmp_path / "site"
    crawl(client, snapshots, day=date(2026, 9, 6), areas=[8], log=lambda s: None)
    build_site(snapshots, site, base_url="https://x.test/f", base_tag="x.test,2026:f")
    footer = (site / "404.html").read_text(encoding="utf-8").split("<footer>")[1]
    issue, mailto = re.findall(r'<a href="([^"]*)">', footer)
    q = parse_qs(urlsplit(html.unescape(issue)).query, keep_blank_values=True)
    assert q["pagina"] == [""] and q["item"] == [""]
    assert q["title"] == ["Problema em Página não encontrada"]
    assert "&amp;body=P%C3%A1gina%3A%20%0AItem%3A%20%0A" in mailto
