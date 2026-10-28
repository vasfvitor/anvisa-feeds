"""The CMED pages: site/cmed/, one Atom feed per substância and per laboratório, plus a general
one, each entry a month of the price list diffed against the previous month.

Built from `snapshots/cmed/` (see cmed.py) by `feeds.build_site`, which calls `build_cmed` and
folds the result into the sitemap and meta.json. The HTML reuses feeds.py's template, CSS and
helpers; what differs is the header links, the footer's provenance and a second XSL for the
feeds, since these sit two directories deep.
"""

from __future__ import annotations

import hashlib
import html
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from anvisa.dados import cmed as reader

from . import feeds
from .cmed import RELEASE_TAG, load_meta, load_rows, stamps
from .cmed_dados import write_dados
from .diff import diff_keyed, summary_keyed

TITLE = "Preços CMED"
SOURCE_URL = "https://www.gov.br/anvisa/pt-br/assuntos/medicamentos/cmed/precos"
DATA_URL = "https://dados.anvisa.gov.br/dados/"
PROVENANCE = (
    f'Dados da CMED/ANVISA (a <a href="{SOURCE_URL}">lista mensal de preços</a>, nos arquivos '
    f'abertos de <a href="{DATA_URL}">dados.anvisa.gov.br</a>), reproduzidos sem alteração. '
    "Preços máximos, não preços praticados; não substitui a lista oficial."
)
# what counts as a change between months: every column but the key, the derived root, the
# publication date, the two "shown but not applicable" flags and the year the comercialização
# column refers to (the header says "COMERCIALIZAÇÃO 2025"; the year it rolls over, every row
# would change)
FIELDS = tuple(
    c
    for c in reader.COLUMNS
    if c
    not in (
        "ggrem",
        "registro_produto",
        "publicado_em",
        "pmc_asterisco",
        "pmvg_asterisco",
        "comercializacao_periodo",
    )
)
# how a non-price field reads in an event; comercialização has its own words (change_li)
FIELD_LABELS = {
    "tarja": "tarja",
    "regime_preco": "regime de preço",
    "restricao_hospitalar": "uso hospitalar",
    "tipo_produto": "tipo",
    "produto": "nome",
    "laboratorio": "laboratório",
    "substancia": "substância",
    "apresentacao": "apresentação",
    "classe_terapeutica": "classe terapêutica",
}
PRICE_FIELDS = ("pf_0", "pmc_0", "pmvg_0")  # the three shown in tables; the rest fold away
# what the JSON files carry per presentation: the full 102 columns are in the Parquet (anvisa-api)
JSON_FIELDS = (
    "ggrem",
    "registro",
    "produto",
    "apresentacao",
    "substancia",
    "cnpj",
    "laboratorio",
    "tipo_produto",
    "regime_preco",
    "tarja",
    *PRICE_FIELDS,
    "restricao_hospitalar",
    "cap",
)
TOP_MOVES = 20
SLUG_MAX = 80  # characters of a substância slug (file name); longer ones get a hash suffix
FILTER_MIN_ROWS = feeds.FILTER_MIN_ROWS


def compact(row: dict | None) -> dict | None:
    return None if row is None else {f: row.get(f) for f in JSON_FIELDS}


def compact_event(e: dict) -> dict:
    return {"type": e["type"], "key": e["key"], "row": compact(e["row"]), "changes": e["changes"]}


def n(value: int) -> str:
    """Thousands with a dot, as Brazil writes them: 26635 -> 26.635."""
    return f"{value:,}".replace(",", ".")


def money(centavos: int | None) -> str:
    if centavos is None:
        return "–"
    reais, cents = divmod(centavos, 100)
    return f"R$ {reais:,}".replace(",", ".") + f",{cents:02d}"


def pct(old: int | None, new: int | None) -> str:
    if not old or new is None:
        return ""
    change = (new - old) / old * 100
    return f"{change:+.1f} %".replace(".", ",")


def month_label(stamp: str) -> str:
    return f"{stamp[6:8]}/{stamp[4:6]}/{stamp[0:4]}"


def nav(root: str) -> list[tuple[str, str]]:
    return [
        (f"{root}cmed/index.html", TITLE),
        (f"{root}index.html", "Todas as filas"),
        (f"{root}cmed/cmed.opml", "OPML"),
    ]


def xsl(base_url: str) -> str:
    """The feed style sheet for cmed/: like feeds.FEED_XSL, with absolute links (the feeds sit
    at two depths) and CMED wording."""
    return (
        feeds.FEED_XSL.replace(
            'href="../index.html">' + feeds.SITE_NAME, f'href="{base_url}/cmed/index.html">{TITLE}'
        )
        .replace(
            '<a href="../index.html">Todas as filas</a>',
            f'<a href="{base_url}/index.html">Todas as filas</a>',
        )
        .replace("as mudanças desta fila", "as mudanças deste feed")
        .replace("página da fila", "página do feed")
        .replace("abra a página da fila", "abra a página do feed")
    )


def row_cells(r: dict, *, group_by: str) -> str:
    """One row of a table of presentations: the column the page groups by is left out."""
    who = r.get("substancia") if group_by == "cnpj" else r.get("laboratorio")
    return (
        f"<td>{html.escape(r.get('produto') or '')}</td>"
        f"<td>{html.escape(r.get('apresentacao') or '')}</td>"
        f"<td>{html.escape(who or '')}</td>"
        + "".join(f'<td class="p">{money(r.get(f))}</td>' for f in PRICE_FIELDS)
        + f'<td class="d">{html.escape(r.get("regime_preco") or "")}</td>'
    )


def rows_table(rows: list[dict], *, group_by: str, caption: str, table_id: str = "") -> str:
    if not rows:
        return f'<p class="empty">{html.escape(caption)}: nenhuma apresentação.</p>'
    who = "Substância" if group_by == "cnpj" else "Laboratório"
    out = [
        f'<table class="queue" id="{table_id}"><caption>{html.escape(caption)}</caption>'
        f"<thead><tr><th>Produto</th><th>Apresentação</th><th>{who}</th><th>PF 0 %</th>"
        '<th>PMC 0 %</th><th>PMVG 0 %</th><th class="d">Regime</th></tr></thead><tbody>'
    ]
    for r in sorted(rows, key=lambda r: (r.get("produto") or "", r.get("apresentacao") or "")):
        out.append(
            f'<tr title="GGREM {html.escape(r["ggrem"])}">{row_cells(r, group_by=group_by)}</tr>'
        )
    out.append("</tbody></table>")
    return "".join(out)


def change_li(e: dict) -> str:
    r = e["row"]
    name = (
        f"<b>{html.escape(r.get('produto') or '')}</b> {html.escape(r.get('apresentacao') or '')}"
    )
    if e["type"] == "entered":
        return f'<li class="entered">{name}: entrou, PF {money(r.get("pf_0"))}</li>'
    if e["type"] == "left":
        return f'<li class="left">{name}: saiu da lista (PF era {money(r.get("pf_0"))})</li>'
    parts = []
    for f, (old, new) in e["changes"].items():
        if f in PRICE_FIELDS:
            parts.append(
                f"{f.split('_')[0].upper()} {money(old)} → {money(new)} {pct(old, new)}".strip()
            )
    other = [f for f in e["changes"] if f not in reader.PRICE_COLUMNS]
    for f in other[:3]:
        old, new = e["changes"][f]
        if f == "comercializacao":
            # the list only says whether a sale was reported in the year: never "descontinuado"
            ano = r.get("comercializacao_periodo") or "o ano da lista"
            parts.append(
                f"sem comercialização informada em {html.escape(ano)}"
                if new == "N"
                else f"com comercialização informada em {html.escape(ano)}"
            )
            continue
        label = FIELD_LABELS.get(f, f)
        parts.append(f"{label}: {html.escape(str(old))} → {html.escape(str(new))}")
    priced = [f for f in e["changes"] if f in reader.PRICE_COLUMNS and f not in PRICE_FIELDS]
    if priced:
        parts.append(f"+{len(priced)} preços por alíquota")
    if len(other) > 3:
        parts.append(f"+{len(other) - 3} campos")
    return f'<li class="moved">{name}: {"; ".join(parts) or "mudou"}</li>'


def events_html(events: list[dict], current: list[dict] | None, *, group_by: str) -> str:
    """A month's events for one group as HTML; with `current`, the group's rows after them.
    Goes into the Atom entry and the page alike."""
    out = ["<p>", html.escape(summary_keyed(events)), "</p>"]
    if events:
        out.append('<ul class="events">' + "".join(change_li(e) for e in events) + "</ul>")
    if current is not None:
        out.append(
            rows_table(
                current,
                group_by=group_by,
                caption=f"Lista atual ({n(len(current))} apresentações)",
                table_id="rows",
            )
        )
    return "".join(out)


def group_events(events: list[dict], by: str) -> dict[str, list[dict]]:
    """Events by group value (substância text or CNPJ); a presentation whose group changed
    between months appears under both the old and the new one."""
    groups: dict[str, list[dict]] = {}
    for e in events:
        keys = {e["row"].get(by)}
        if e["old"] is not None:
            keys.add(e["old"].get(by))
        for k in keys:
            if k:
                groups.setdefault(k, []).append(e)
    return groups


def unique_slugs(names: list[str]) -> dict[str, str]:
    """A slug per name; a collision gets a numeric suffix, by sorted name, so it is stable."""
    out: dict[str, str] = {}
    taken: Counter = Counter()
    for name in sorted(names):
        base = feeds.slug(name)
        if len(base) > SLUG_MAX:  # parenteral nutrition lists twenty actives: keep file names sane
            base = (
                base[: SLUG_MAX - 7].rstrip("-") + "-" + hashlib.sha1(name.encode()).hexdigest()[:6]
            )
        taken[base] += 1
        out[name] = base if taken[base] == 1 else f"{base}-{taken[base]}"
    return out


def build_cmed(
    snapshots: Path,
    site: Path,
    *,
    base_url: str,
    base_tag: str,
    months: int = 12,
    warn: str = "",
) -> dict | None:
    """Write site/cmed/: index, geral feed, one feed/page/json per substância and per
    laboratório, cmed.opml and feed.xsl. None when there are no CMED snapshots yet."""
    known = stamps(snapshots)
    if not known:
        return None
    window = known[-(months + 1) :]
    base_url = base_url.rstrip("/")
    out = Path(site) / "cmed"
    for sub in ("substancia", "laboratorio"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    (out / "feed.xsl").write_text(xsl(base_url), encoding="utf-8")
    metas = {s: load_meta(snapshots, s) for s in window}

    # month over month: events per stamp, oldest first; the latest rows kept for the tables
    history: list[tuple[str, list[dict]]] = []
    prev: dict[str, dict] | None = None
    for stamp in window:
        curr = load_rows(snapshots, stamp)
        if prev is not None:
            history.append((stamp, diff_keyed(prev, curr, FIELDS)))
        prev = curr
    latest_stamp, latest = window[-1], prev or {}
    if not history:
        history = [(latest_stamp, [])]  # the first list ever: no diff yet
    meta = metas[latest_stamp]
    fetched = datetime.fromisoformat(meta["fetched"]).strftime("%Y-%m-%d %H:%M")
    stamp_text = (
        f"Última lista: {month_label(latest_stamp)} ({n(meta['rows'])} apresentações), lida em "
        f"{fetched} (horário de Brasília)."
    )
    org = {"@type": "Organization", "name": "anvisa-feeds", "url": feeds.REPO_URL}
    pages: list[tuple[str, str]] = []
    by_month = {stamp: events for stamp, events in history}
    newest_stamp, newest_events = history[-1]

    def feed_entries(
        events_by_month: dict[str, list[dict]],
        current: list[dict] | None,
        *,
        kind: str,
        ident: str,
        group_by: str,
    ) -> list[dict]:
        entries = []
        for stamp, _ in reversed(history):
            events = events_by_month.get(stamp, [])
            entries.append(
                {
                    "id": feeds.tag_uri(base_tag, "cmed", kind, ident, stamp),
                    "title": f"Lista de {month_label(stamp)}: {summary_keyed(events)}",
                    "updated": metas[stamp]["fetched"],
                    "link": f"{base_url}/cmed/{kind}/{ident}.html"
                    if ident
                    else f"{base_url}/cmed/geral.html",
                    "content": events_html(
                        events, current if stamp == newest_stamp else None, group_by=group_by
                    ),
                }
            )
        return entries

    def write_group(
        kind: str,
        ident: str,
        name: str,
        current: list[dict],
        events_by_month: dict[str, list[dict]],
        *,
        group_by: str,
        extra: str,
    ) -> None:
        feed_url = f"{base_url}/cmed/{kind}/{ident}.xml"
        page_url = f"{base_url}/cmed/{kind}/{ident}.html"
        entries = feed_entries(events_by_month, current, kind=kind, ident=ident, group_by=group_by)
        (out / kind / f"{ident}.xml").write_bytes(
            feeds.atom_feed(
                feed_id=feeds.tag_uri(base_tag, "cmed", kind, ident),
                title=f"Preços CMED: {name}",
                self_url=feed_url,
                alt_url=page_url,
                updated=entries[0]["updated"],
                entries=entries,
                xsl_href="../feed.xsl",
                author="anvisa-feeds (dados: CMED/ANVISA)",
            )
        )
        count = len(current)
        section = "Substâncias" if kind == "substancia" else "Laboratórios"
        heading = (
            '<nav class="crumbs" aria-label="Você está em">'
            f'<a href="../index.html">{TITLE}</a><span>›</span>'
            f"<a "
            f'href="../index.html#{kind}">{section}</a></nav>'
            f"<h1>{html.escape(name)}</h1>"
            f'<p class="meta"><span>{n(count)} apresentações na lista de '
            f"{month_label(latest_stamp)}</span>{extra}"
            f'<a class="pill" href="{ident}.xml" title="Cole este endereço no seu leitor de '
            f'feeds">Feed Atom</a>'
            f'<button class="pill copy" type="button" data-copy="{feed_url}" hidden>Copiar '
            f"endereço do feed</button>"
            f'<a class="pill" href="{ident}.json" title="As apresentações em JSON">JSON</a></p>'
        )
        (out / kind / f"{ident}.json").write_text(
            json.dumps(
                {
                    kind: name,
                    "lista": latest_stamp,
                    "publicado_em": meta["publicado_em"],
                    "pagina": page_url,
                    "feed": feed_url,
                    "mudancas": [compact_event(e) for e in events_by_month.get(newest_stamp, [])],
                    "apresentacoes": [compact(r) for r in current],
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        body = warn + f"<h2>Mudanças na lista de {month_label(newest_stamp)}</h2>"
        content = entries[0]["content"]
        table_block = ""
        if count >= FILTER_MIN_ROWS and '<table class="queue"' in content:
            i = content.index('<table class="queue"')
            content, table_block = content[:i], content[i:]
            table_block = (
                feeds.filter_box("#rows", "tbody tr", "Filtrar por produto ou apresentação")
                + table_block
            )
        body += content + table_block + history_html(history[:-1], events_by_month)
        description = (
            f"Preços máximos de medicamentos da CMED, {name}: {count} apresentações na lista de "
            f"{month_label(latest_stamp)}. Feed Atom com o que entrou, saiu e mudou de preço a "
            f"cada lista."
        )
        crumbs = {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": TITLE, "item": f"{base_url}/cmed/"},
                {"@type": "ListItem", "position": 2, "name": name},
            ],
        }
        (out / kind / f"{ident}.html").write_text(
            feeds.page(
                f"{name} · {TITLE}",
                body,
                stamp=stamp_text,
                url=page_url,
                description=description,
                root="../../",
                feed_url=feed_url,
                extra_head=feeds.json_ld(crumbs),
                heading=heading,
                nav=nav("../../"),
                provenance=PROVENANCE,
            ),
            encoding="utf-8",
        )
        pages.append((page_url, meta["fetched"]))

    # substâncias
    by_subst: dict[str, list[dict]] = {}
    for r in latest.values():
        if r.get("substancia"):
            by_subst.setdefault(r["substancia"], []).append(r)
    subst_events = {stamp: group_events(events, "substancia") for stamp, events in history}
    subst_names = sorted(set(by_subst) | {k for g in subst_events.values() for k in g})
    subst_slug = unique_slugs(subst_names)
    for name in subst_names:
        write_group(
            "substancia",
            subst_slug[name],
            name,
            by_subst.get(name, []),
            {stamp: g.get(name, []) for stamp, g in subst_events.items()},
            group_by="substancia",
            extra="",
        )

    # laboratórios, by CNPJ; the name is the latest row's
    by_lab: dict[str, list[dict]] = {}
    lab_name: dict[str, str] = {}
    for r in latest.values():
        if r.get("cnpj"):
            by_lab.setdefault(r["cnpj"], []).append(r)
            lab_name.setdefault(r["cnpj"], r.get("laboratorio") or r["cnpj"])
    lab_events = {stamp: group_events(events, "cnpj") for stamp, events in history}
    for g in lab_events.values():
        for cnpj, evs in g.items():
            lab_name.setdefault(cnpj, (evs[0]["old"] or evs[0]["row"]).get("laboratorio") or cnpj)
    for cnpj in sorted(set(by_lab) | {k for g in lab_events.values() for k in g}):
        write_group(
            "laboratorio",
            cnpj,
            lab_name[cnpj],
            by_lab.get(cnpj, []),
            {stamp: g.get(cnpj, []) for stamp, g in lab_events.items()},
            group_by="cnpj",
            extra=f"<span>CNPJ {cnpj}</span>",
        )

    # the general feed: every event of the month, no table (the index has the highlights)
    general_entries = feed_entries(by_month, None, kind="geral", ident="", group_by="substancia")
    (out / "geral.xml").write_bytes(
        feeds.atom_feed(
            feed_id=feeds.tag_uri(base_tag, "cmed", "geral"),
            title="Preços CMED: todas as mudanças",
            self_url=f"{base_url}/cmed/geral.xml",
            alt_url=f"{base_url}/cmed/index.html",
            updated=general_entries[0]["updated"],
            entries=general_entries,
            xsl_href="feed.xsl",
            author="anvisa-feeds (dados: CMED/ANVISA)",
        )
    )

    # index: highlights of the month, then every substância and laboratório
    counts = Counter(e["type"] for e in newest_events)
    moves = [
        (e, e["changes"]["pf_0"][0], e["changes"]["pf_0"][1])
        for e in newest_events
        if e["type"] == "changed"
        and "pf_0" in e["changes"]
        and e["changes"]["pf_0"][0]
        and e["changes"]["pf_0"][1] is not None
    ]
    moves.sort(key=lambda m: (m[2] - m[1]) / m[1])
    release_url = f"{feeds.REPO_URL}/releases/tag/{RELEASE_TAG.format(stamp=latest_stamp)}"
    index_description = (
        f"Preços máximos de medicamentos da CMED: {n(meta['rows'])} apresentações, "
        f"{n(len(subst_names))} substâncias, {n(len(by_lab))} laboratórios, lista de "
        f"{month_label(latest_stamp)}. Um feed Atom por substância e por laboratório com o que "
        "entrou, saiu e mudou de preço a cada lista mensal."
    )
    lines = [
        warn,
        f'<p class="lead">A <strong>lista mensal de preços máximos de medicamentos da '
        f"CMED</strong>, "
        f"{n(meta['rows'])} apresentações de {n(len(subst_names))} substâncias e {len(by_lab)} "
        f"laboratórios, "
        f"comparada com a lista anterior a cada mês. Lista de {month_label(latest_stamp)}"
        + (
            f"; na anterior, {summary_keyed(newest_events)}."
            if len(window) > 1
            else "; a primeira lista guardada, sem comparação ainda."
        )
        + "</p>",
        '<div class="box"><strong>Como acompanhar.</strong> Abra a substância (o princípio ativo) '
        "ou o "
        "laboratório abaixo: a página lista as apresentações com PF, PMC e PMVG à alíquota 0 % e o "
        "que "
        "mudou na última lista. Para receber as mudanças, copie o endereço do <em>feed</em> e cole "
        "no seu "
        'leitor. Tudo de uma vez: o <a href="geral.xml">feed geral</a> ou o <a '
        'href="cmed.opml">OPML</a>. '
        "Cada página também existe em JSON. Os arquivos originais de cada mês ficam na "
        f"<a "
        f'href="{release_url}">release</a> '
        "do repositório; a tabela completa, em Parquet, no "
        '<a href="https://vasfvitor.github.io/anvisa-api/">anvisa-api</a>.</div>',
        '<div class="box">PF é o preço fábrica, o teto do laboratório; PMC o preço máximo ao '
        "consumidor, "
        "o teto na farmácia; PMVG o preço máximo de venda ao governo. A CMED reajusta a lista uma "
        "vez por "
        "ano, em março ou abril: nesse mês quase tudo muda.</div>",
    ]
    if moves:
        lines.append(f"<h2>Maiores altas de PF na lista de {month_label(newest_stamp)}</h2>")
        lines.append(moves_table(list(reversed(moves))[:TOP_MOVES], subst_slug))
        lines.append(f"<h2>Maiores baixas de PF na lista de {month_label(newest_stamp)}</h2>")
        lines.append(moves_table(moves[:TOP_MOVES], subst_slug))
    if counts["entered"] or counts["left"]:
        lines.append(f"<h2>Entradas e saídas na lista de {month_label(newest_stamp)}</h2>")
        lines.append(
            '<ul class="events">'
            + "".join(change_li(e) for e in newest_events if e["type"] != "changed")
            + "</ul>"
        )
    lines.append(
        '<nav class="toc" aria-label="Seções"><a href="#substancia">Substâncias<span class="n">'
        f'{len(subst_names)}</span></a><a href="#laboratorio">Laboratórios<span '
        f'class="n">{len(by_lab)}</span></a></nav>'
    )
    lines.append(feeds.filter_box("#grupos", "ul.filas li", "Filtrar substâncias e laboratórios"))
    lines.append('<div id="grupos">')
    lines.append('<section id="substancia" data-group><h2>Substâncias</h2><ul class="filas">')
    for name in subst_names:
        k = len(by_subst.get(name, []))
        lines.append(
            f'<li><span class="t"><a '
            f'href="substancia/{subst_slug[name]}.html">{html.escape(name)}</a></span>'
            f'<span class="n{"" if k else " zero"}">{f"{k} apres." if k else "saiu"}</span>'
            f'<a class="feed" href="substancia/{subst_slug[name]}.xml" title="Feed Atom desta '
            f'substância">feed</a></li>'
        )
    lines.append("</ul></section>")
    lines.append('<section id="laboratorio" data-group><h2>Laboratórios</h2><ul class="filas">')
    for cnpj in sorted(lab_name, key=lambda c: lab_name[c]):
        k = len(by_lab.get(cnpj, []))
        lines.append(
            f'<li><span class="t"><a '
            f'href="laboratorio/{cnpj}.html">{html.escape(lab_name[cnpj])}</a></span>'
            f'<span class="n{"" if k else " zero"}">{f"{k} apres." if k else "saiu"}</span>'
            f'<a class="feed" href="laboratorio/{cnpj}.xml" title="Feed Atom deste '
            f'laboratório">feed</a></li>'
        )
    lines.append("</ul></section></div>")
    lines += [
        '<section id="faq"><h2>Perguntas frequentes</h2>',
        "<h3>De onde vêm os preços?</h3>",
        f'<p>Da lista que a CMED publica em <a href="{SOURCE_URL}">gov.br</a>, nos dois arquivos '
        f"abertos "
        "(PMC e PMVG) que a ANVISA republica. São os preços máximos; o preço praticado é menor ou "
        "igual.</p>",
        "<h3>O que é “mudou”?</h3>",
        "<p>Qualquer campo da apresentação diferente entre a lista deste mês e a do mês anterior: "
        "preço em "
        "qualquer alíquota, regime, tarja, lista PIS/COFINS, laboratório, nome.</p>",
        "<h3>Por que quase tudo muda em março ou abril?</h3>",
        "<p>É o reajuste anual autorizado pela CMED. A lista desse mês traz quase todos os preços "
        "alterados.</p>",
        "<h3>Isto é um serviço da ANVISA ou da CMED?</h3>",
        f'<p>Não. É um projeto independente e de <a href="{feeds.REPO_URL}">código aberto</a> que '
        f"republica "
        "os dados públicos sem alteração. Não substitui a lista oficial.</p></section>",
    ]
    dataset = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": "Preços CMED: lista mensal em feeds",
        "description": index_description,
        "url": f"{base_url}/cmed/",
        "sameAs": feeds.REPO_URL,
        "license": "https://opensource.org/licenses/MIT",
        "isBasedOn": SOURCE_URL,
        "creator": org,
        "publisher": org,
        "inLanguage": "pt-BR",
        "keywords": [
            "ANVISA",
            "CMED",
            "preço máximo",
            "medicamentos",
            "PMC",
            "PMVG",
            "preço fábrica",
        ],
        "spatialCoverage": {"@type": "Place", "name": "Brasil"},
        "temporalCoverage": f"{known[0][:4]}-{known[0][4:6]}-{known[0][6:]}/..",
        "dateModified": meta["fetched"],
        "isAccessibleForFree": True,
        "distribution": [
            {
                "@type": "DataDownload",
                "encodingFormat": "text/x-opml",
                "contentUrl": f"{base_url}/cmed/cmed.opml",
            },
            {
                "@type": "DataDownload",
                "encodingFormat": "application/atom+xml",
                "contentUrl": f"{base_url}/cmed/geral.xml",
            },
        ],
    }
    (out / "index.html").write_text(
        feeds.page(
            TITLE,
            "".join(lines),
            stamp=stamp_text,
            url=f"{base_url}/cmed/",
            description=index_description,
            root="../",
            feed_url=f"{base_url}/cmed/geral.xml",
            extra_head=feeds.json_ld(dataset),
            nav=nav("../"),
            provenance=PROVENANCE,
        ),
        encoding="utf-8",
    )
    pages.insert(0, (f"{base_url}/cmed/", meta["fetched"]))

    # OPML: geral, then substâncias and laboratórios
    opml = ET.Element("opml", version="2.0")
    ET.SubElement(ET.SubElement(opml, "head"), "title").text = TITLE
    body_el = ET.SubElement(opml, "body")
    ET.SubElement(
        body_el,
        "outline",
        text="Todas as mudanças",
        type="rss",
        xmlUrl=f"{base_url}/cmed/geral.xml",
        htmlUrl=f"{base_url}/cmed/index.html",
    )
    subst_el = ET.SubElement(body_el, "outline", text="Substâncias")
    for name in subst_names:
        ET.SubElement(
            subst_el,
            "outline",
            text=name,
            type="rss",
            xmlUrl=f"{base_url}/cmed/substancia/{subst_slug[name]}.xml",
            htmlUrl=f"{base_url}/cmed/substancia/{subst_slug[name]}.html",
        )
    lab_el = ET.SubElement(body_el, "outline", text="Laboratórios")
    for cnpj in sorted(lab_name, key=lambda c: lab_name[c]):
        ET.SubElement(
            lab_el,
            "outline",
            text=lab_name[cnpj],
            type="rss",
            xmlUrl=f"{base_url}/cmed/laboratorio/{cnpj}.xml",
            htmlUrl=f"{base_url}/cmed/laboratorio/{cnpj}.html",
        )
    (out / "cmed.opml").write_bytes(feeds.xml_bytes(opml))
    # data for the public portal: one JSON per product with the PMC at every ICMS rate
    # (meta.json is a contract with anvisa-hub: the count is not added to the returned block)
    write_dados(
        out,
        latest,
        stamp=latest_stamp,
        publicado_em=meta["publicado_em"],
        feeds={n: f"{base_url}/cmed/substancia/{s}.xml" for n, s in subst_slug.items()},
    )

    return {
        "stamp": latest_stamp,
        "publicado_em": meta["publicado_em"],
        "fetched": meta["fetched"],
        "rows": meta["rows"],
        "substancias": len(subst_names),
        "laboratorios": len(lab_name),
        "feeds": 1 + len(subst_names) + len(lab_name),
        "months": len(window),
        "first_stamp": known[0],
        "events": {k: counts[k] for k in ("entered", "changed", "left")},
        "release": RELEASE_TAG.format(stamp=latest_stamp),
        "destaques": {
            "altas": [highlight(m, subst_slug, base_url) for m in list(reversed(moves))[:5]],
            "baixas": [highlight(m, subst_slug, base_url) for m in moves[:5]],
            "entradas": [
                highlight((e, None, e["row"].get("pf_0")), subst_slug, base_url)
                for e in newest_events
                if e["type"] == "entered"
            ][:5],
            "saidas": [
                highlight((e, e["row"].get("pf_0"), None), subst_slug, base_url)
                for e in newest_events
                if e["type"] == "left"
            ][:5],
        },
        "pages": pages,
    }


def highlight(
    move: tuple[dict, int | None, int | None], subst_slug: dict[str, str], base_url: str
) -> dict:
    """One presentation for the hub: what it is, the PF before and after, where to read more."""
    e, old, new = move
    r = e["row"]
    s = r.get("substancia") or ""
    return {
        "produto": r.get("produto"),
        "apresentacao": r.get("apresentacao"),
        "substancia": s,
        "laboratorio": r.get("laboratorio"),
        "pf_de": old,
        "pf_para": new,
        "variacao": round((new - old) / old * 100, 1) if old and new is not None else None,
        "pagina": f"{base_url}/cmed/substancia/{subst_slug[s]}.html" if s in subst_slug else None,
    }


def moves_table(moves: list[tuple[dict, int, int]], subst_slug: dict[str, str]) -> str:
    out = [
        '<table class="queue"><thead><tr><th>Produto</th><th>Apresentação</th><th>Substância</th>'
        '<th>PF antes</th><th>PF depois</th><th class="d">Variação</th></tr></thead><tbody>'
    ]
    for e, old, new in moves:
        r = e["row"]
        s = r.get("substancia") or ""
        link = (
            f'<a href="substancia/{subst_slug[s]}.html">{html.escape(s)}</a>'
            if s in subst_slug
            else html.escape(s)
        )
        out.append(
            f"<tr><td>{html.escape(r.get('produto') or '')}</td>"
            f"<td>{html.escape(r.get('apresentacao') or '')}</td>"
            f'<td>{link}</td><td class="p">{money(old)}</td><td class="p">{money(new)}</td>'
            f'<td class="d">{pct(old, new)}</td></tr>'
        )
    out.append("</tbody></table>")
    return "".join(out)


def history_html(
    earlier: list[tuple[str, list[dict]]], events_by_month: dict[str, list[dict]]
) -> str:
    """Earlier months on a group's page, newest first: the summary, the events on demand."""
    if not earlier:
        return ""
    out = ["<h2>Listas anteriores</h2>", '<ul class="days">']
    for stamp, _ in reversed(earlier):
        events = events_by_month.get(stamp, [])
        label = f"<b>{month_label(stamp)}</b> {html.escape(summary_keyed(events))}"
        if events:
            items = '<ul class="events">' + "".join(change_li(e) for e in events) + "</ul>"
            out.append(f"<li><details><summary>{label}</summary>{items}</details></li>")
        else:
            out.append(f'<li class="quiet">{label}</li>')
    out.append("</ul>")
    return "".join(out)
