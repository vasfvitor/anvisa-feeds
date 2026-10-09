"""Build the static site: one Atom feed and one HTML page per subfila, plus an index.

Feeds are regenerated from the last N snapshots on every build. An entry is one subfila on
one day and lists that day's events; only the newest entry also carries the queue as it
stands, so a feed stays small however long the window. Snapshots are read one day at a time.

The HTML is deliberately plain: one inline style sheet, one short inline script that only adds
filtering on top of a page that already works without it, no external assets.
"""

from __future__ import annotations

import html
import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from . import __version__
from .crawl import describe, load_catalog, load_meta, load_snapshot, snapshot_days
from .diff import diff_snapshots, summary

ATOM = "http://www.w3.org/2005/Atom"
SITEMAP = "http://www.sitemaps.org/schemas/sitemap/0.9"
SITE_NAME = "Filas de análise da ANVISA"
REPO_URL = "https://github.com/vasfvitor/anvisa-feeds"
FILTER_MIN_ROWS = 12  # below this a filter box is noise
FOLD_MOVED_ABOVE = 8  # more position changes than this fold into a <details>

# A small, intentional palette: one accent, two semantic colours for entered/left, the rest
# greys. Variables so dark mode is one block, not a second style sheet.
CSS = """
:root{--bg:#fff;--fg:#1d1d1f;--muted:#6b7280;--line:#e5e7eb;--soft:#f6f7f9;--accent:#1d4ed8;
--up:#15803d;--down:#b91c1c;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media(prefers-color-scheme:dark){:root{--bg:#111214;--fg:#e7e7ea;--muted:#9ca3af;
--line:#2a2c31;--soft:#1a1c20;--accent:#7aa2ff;--up:#4ade80;--down:#f87171}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,
"Segoe UI",Roboto,sans-serif;font-variant-numeric:tabular-nums}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:64rem;margin:0 auto;padding:0 1rem}
.site{border-bottom:1px solid var(--line)}.site .wrap{display:flex;flex-wrap:wrap;gap:.5rem 1.5rem;
align-items:baseline;padding:.75rem 1rem}.site .name{font-weight:600;color:var(--fg)}
.site nav{margin-left:auto;display:flex;gap:1rem;font-size:.9em}
main{padding:1.25rem 0 2rem}
h1{font-size:1.5rem;line-height:1.25;margin:.25rem 0 .5rem;font-weight:650;letter-spacing:-.01em}
h2{font-size:1.05rem;margin:2rem 0 .5rem;padding-bottom:.25rem;border-bottom:1px solid var(--line)}
h3{font-size:.95rem;margin:1.25rem 0 .25rem;color:var(--muted);font-weight:600}
p{margin:.5rem 0}code{font:.92em var(--mono)}
.crumbs{font-size:.85em;color:var(--muted);margin:0 0 .25rem}.crumbs a{color:var(--muted)}
.crumbs span{margin:0 .35em}
.meta{color:var(--muted);font-size:.9em;display:flex;flex-wrap:wrap;gap:.35rem .75rem;
align-items:center}
.pill{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:.1rem .6rem;
font-size:.85em;color:var(--accent);background:var(--soft)}.pill:hover{text-decoration:none;
border-color:var(--accent)}
.box.warn{border-left-color:var(--down);font-weight:600}
.box{background:var(--soft);border-left:3px solid var(--accent);padding:.75rem 1rem;margin:1rem 0;
border-radius:0 4px 4px 0}
.lead{font-size:1.05em;max-width:46rem}
.toc{display:flex;flex-wrap:wrap;gap:.35rem .5rem;margin:1rem 0;font-size:.9em}
.toc a{border:1px solid var(--line);border-radius:4px;padding:.15rem .5rem;color:var(--fg)}
.toc a:hover{border-color:var(--accent);text-decoration:none}.toc .n{color:var(--muted);
margin-left:.35em}
.filter{display:none;width:100%;max-width:28rem;margin:.75rem 0;padding:.45rem .65rem;font:inherit;
color:var(--fg);background:var(--bg);border:1px solid var(--line);border-radius:4px}
.filter:focus{outline:2px solid var(--accent);outline-offset:1px;border-color:transparent}
.js .filter{display:block}.hint{color:var(--muted);font-size:.85em;margin:.25rem 0 0}
ul.filas{list-style:none;margin:0;padding:0}
ul.filas li{display:flex;gap:.75rem;align-items:baseline;padding:.3rem 0;
border-bottom:1px solid var(--line)}
ul.filas li:last-child{border-bottom:0}ul.filas .t{flex:1;min-width:0}
ul.filas .n{min-width:9ch;text-align:right;color:var(--fg);font-size:.9em;white-space:nowrap}
ul.filas .n.zero{color:var(--muted)}ul.filas .feed{font-size:.85em;color:var(--muted)}
ul.filas .feed:hover{color:var(--accent)}
.hide{display:none!important}
ul.events{list-style:none;padding:0;margin:.5rem 0}ul.events li{padding:.2rem 0 .2rem 1.4rem;
position:relative}
ul.events li::before{position:absolute;left:0;font:600 .9em var(--mono);color:var(--muted)}
ul.events .entered::before{content:"+";color:var(--up)}ul.events .left::before{content:"−";
color:var(--down)}
ul.events .moved::before{content:"↕"}ul.events small{color:var(--muted)}
details{margin:.5rem 0}summary{cursor:pointer;color:var(--muted)}summary:hover{color:var(--fg)}
ul.days{list-style:none;padding:0;margin:0}
ul.days>li{padding:.25rem 0;border-bottom:1px solid var(--line)}
ul.days details{margin:0}ul.days summary{color:var(--fg)}ul.days .quiet{color:var(--muted)}
ul.days b{font-weight:600;margin-right:.5em}.copy{cursor:pointer;font:inherit;font-size:.85em}
.copy.done{color:var(--up);border-color:var(--up)}
table.queue{width:100%;border-collapse:collapse;margin:.5rem 0 1rem;font-size:.95em}
table.queue caption{text-align:left;font-weight:600;padding:.5rem 0;caption-side:top}
table.queue th{text-align:left;font-weight:600;color:var(--muted);font-size:.85em;
border-bottom:1px solid var(--line);padding:.35rem .5rem .35rem 0}
table.queue td{padding:.35rem .5rem .35rem 0;border-bottom:1px solid var(--line);vertical-align:top}
table.queue td:first-child,table.queue th:first-child{text-align:right;color:var(--muted);width:4ch;
padding-right:.75rem}table.queue td.p{white-space:nowrap}table.queue td.d{white-space:nowrap;
color:var(--muted)}
.empty{color:var(--muted);font-style:italic}
footer{border-top:1px solid var(--line);color:var(--muted);font-size:.85em;padding:1rem 0 2rem}
footer p{margin:.25rem 0}
.entry{margin:1.5rem 0}
@media(max-width:40rem){table.queue td.d,table.queue th.d{display:none}h1{font-size:1.3rem}}
""".strip()

# Progressive enhancement only: the pages work without this. It reveals the filter boxes,
# filters rows/items by text, hides groups and sections left empty, and keeps a count.
JS = """
document.documentElement.classList.add('js');
document.querySelectorAll('input.filter').forEach(function(inp){
  var root=document.querySelector(inp.dataset.target), hint=inp.nextElementSibling;
  var items=Array.prototype.slice.call(root.querySelectorAll(inp.dataset.items));
  var norm=function(s){return s.normalize('NFD').replace(/[\\u0300-\\u036f]/g,'').toLowerCase();};
  var texts=items.map(function(el){return norm(el.textContent);});
  inp.addEventListener('input',function(){
    var q=norm(inp.value.trim()), shown=0;
    items.forEach(function(el,i){var ok=!q||texts[i].indexOf(q)>-1;
el.classList.toggle('hide',!ok);shown+=ok;});
    root.querySelectorAll('[data-group]').forEach(function(g){
      g.classList.toggle('hide',!g.querySelector(inp.dataset.items+':not(.hide)'));});
    if(hint)hint.textContent=q?shown+' de '+items.length:'';
  });
});
if(navigator.clipboard)document.querySelectorAll('button.copy').forEach(function(b){
  b.hidden=false;b.addEventListener('click',function(){
    navigator.clipboard.writeText(b.dataset.copy).then(function(){
      b.textContent='Copiado';b.classList.add('done');});});});
document.addEventListener('keydown',function(e){
  var f=document.querySelector('input.filter');
  if(f&&e.key==='/'&&document.activeElement!==f){e.preventDefault();f.focus();}});
""".strip()

FEED_XSL = f"""<?xml version="1.0" encoding="utf-8"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
  xmlns:atom="http://www.w3.org/2005/Atom" exclude-result-prefixes="atom">
<xsl:output method="html" encoding="utf-8" indent="yes"/>
<xsl:template match="/">
<html lang="pt-BR"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title><xsl:value-of select="atom:feed/atom:title"/></title>
<style>{CSS}</style></head>
<body>
<header class="site"><div class="wrap"><a class="name" href="../index.html">{SITE_NAME}</a>
<nav><a href="../index.html">Todas as filas</a></nav></div></header>
<main class="wrap">
<h1><xsl:value-of select="atom:feed/atom:title"/></h1>
<div class="box"><strong>Isto é um feed Atom.</strong> Para receber as mudanças desta fila, copie o
endereço desta página e cole no seu leitor de feeds (Feedly, Inoreader, NetNewsWire, Thunderbird…).
A versão para ler no navegador está em
<a><xsl:attribute name="href">
<xsl:value-of select="atom:feed/atom:link[@rel='alternate']/@href"/>
</xsl:attribute>página da fila</a>.</div>
<h2>Entradas do feed</h2>
<ul class="days">
<xsl:for-each select="atom:feed/atom:entry">
<li><a><xsl:attribute name="href">
<xsl:value-of select="atom:link[@rel='alternate']/@href"/></xsl:attribute>
<xsl:value-of select="atom:title"/></a></li>
</xsl:for-each>
</ul>
<p class="hint">O conteúdo de cada entrada aparece no seu leitor de feeds;
no navegador, abra a página da fila.</p>
</main>
</body></html>
</xsl:template>
</xsl:stylesheet>
"""


def tag_uri(base_tag: str, *parts: str) -> str:
    return f"tag:{base_tag}:" + "/".join(parts)


def slug(text: str) -> str:
    """ASCII anchor id: 'Dispositivos Médicos' → 'dispositivos-medicos'."""
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-") or "x"


def q(s: str) -> str:
    return html.escape(s, quote=True)


def events_html(events: list[dict], queue: list[dict] | None = None) -> str:
    """The day's events as HTML; with `queue`, the current queue after them. This goes into
    the Atom entry as well as the page, so it stays semantic HTML that reads fine unstyled."""
    out = ["<p>", html.escape(summary(events)), "</p>"]
    # entries and exits are the news; position changes are mostly the queue closing a gap,
    # so they fold away when there are many (a reader without CSS/JS still shows them all)
    changes = [e for e in events if e["type"] != "moved"]
    moved = [e for e in events if e["type"] == "moved"]
    if changes:
        out.append('<ul class="events">' + "".join(event_li(e) for e in changes) + "</ul>")
    if moved:
        items = '<ul class="events">' + "".join(event_li(e) for e in moved) + "</ul>"
        if len(moved) > FOLD_MOVED_ABOVE:
            items = f"<details><summary>{len(moved)} mudaram de posição</summary>{items}</details>"
        out.append(items)
    if queue is not None:
        out.append(queue_html(queue))
    return "".join(out)


def event_li(e: dict) -> str:
    p = f"<code>{html.escape(e['processo'] or '?')}</code>"
    if e["expediente"]:
        p += f" <small>exp. {html.escape(e['expediente'])}</small>"
    if e["type"] == "entered":
        return f'<li class="entered">{p}: entrou na posição {e["para"]}</li>'
    if e["type"] == "left":
        return f'<li class="left">{p}: saiu da fila (estava na posição {e["de"]})</li>'
    return f'<li class="moved">{p}: {e["de"]} → {e["para"]}</li>'


def history_html(days_events: list[tuple[date, list[dict]]]) -> str:
    """Earlier days on the page, newest first: the summary, and entries/exits on demand.
    Position changes are only counted; the feed has them in full."""
    if not days_events:
        return ""
    out = ["<h2>Dias anteriores</h2>", '<ul class="days">']
    for day, events in reversed(days_events):
        changes = [e for e in events if e["type"] != "moved"]
        label = f"<b>{day.isoformat()}</b> {html.escape(summary(events))}"
        if changes:
            items = '<ul class="events">' + "".join(event_li(e) for e in changes) + "</ul>"
            out.append(f"<li><details><summary>{label}</summary>{items}</details></li>")
        else:
            out.append(f'<li class="quiet">{label}</li>')
    out.append("</ul>")
    return "".join(out)


def queue_html(queue: list[dict]) -> str:
    caption = f"Fila hoje ({len(queue)} processos)"
    if not queue:
        return f'<p class="empty">{caption}: nenhum processo aguardando análise.</p>'
    rows = [
        f'<table class="queue" id="queue"><caption>{caption}</caption>'
        '<thead><tr><th>#</th><th>Processo</th><th>Assunto</th><th class="d">Entrada</th></tr>'
        "</thead><tbody>"
    ]
    for r in queue:
        rows.append(
            f'<tr><td>{r["posicao"]}</td><td class="p"><code>{html.escape(r["processo"] or "")}'
            f"</code></td><td>{html.escape(r['dsAssunto'] or '')}</td>"
            f'<td class="d">{r["entrada"] or "?"}</td></tr>'
        )
    rows.append("</tbody></table>")
    return "".join(rows)


def filter_box(target: str, items: str, placeholder: str) -> str:
    return (
        f'<input class="filter" type="search" data-target="{target}" data-items="{items}" '
        f'placeholder="{q(placeholder)}" aria-label="{q(placeholder)}"><p class="hint"></p>'
    )


def atom_feed(
    *, feed_id: str, title: str, self_url: str, alt_url: str, updated: str, entries: list[dict]
) -> bytes:
    feed = ET.Element("feed", xmlns=ATOM)
    ET.SubElement(feed, "id").text = feed_id
    ET.SubElement(feed, "title").text = title
    ET.SubElement(feed, "updated").text = updated
    ET.SubElement(feed, "link", rel="self", href=self_url)
    ET.SubElement(feed, "link", rel="alternate", href=alt_url)
    ET.SubElement(feed, "generator", version=__version__).text = "anvisa-feeds"
    ET.SubElement(ET.SubElement(feed, "author"), "name").text = "anvisa-feeds (dados: ANVISA)"
    for e in entries:
        entry = ET.SubElement(feed, "entry")
        ET.SubElement(entry, "id").text = e["id"]
        ET.SubElement(entry, "title").text = e["title"]
        ET.SubElement(entry, "updated").text = e["updated"]
        ET.SubElement(entry, "link", rel="alternate", href=e["link"])
        ET.SubElement(entry, "content", type="html").text = e["content"]
    # the stylesheet makes a browser show a readable page instead of raw XML; readers ignore it.
    # It lists entries as links only: rendering their HTML needs disable-output-escaping, which
    # Firefox does not support (it would print the tags as text).
    return (
        b'<?xml version="1.0" encoding="utf-8"?>\n'
        b'<?xml-stylesheet type="text/xsl" href="../feed.xsl"?>\n'
        + ET.tostring(feed, encoding="unicode").encode("utf-8")
    )


def page(
    title: str,
    body: str,
    *,
    stamp: str,
    url: str,
    description: str,
    root: str,
    feed_url: str | None = None,
    extra_head: str = "",
    heading: str | None = None,
) -> str:
    """The one HTML template. `url` is the canonical address; `feed_url` makes readers find the
    Atom feed from the page; `extra_head` is for JSON-LD; `root` is the relative path to the
    site root ('' on the index, '../' under fila/)."""
    head = [
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta name="color-scheme" content="light dark">',
        '<meta name="theme-color" content="#fff" media="(prefers-color-scheme: light)">',
        '<meta name="theme-color" content="#111214" media="(prefers-color-scheme: dark)">',
        f"<title>{q(title)}</title>",
        f'<meta name="description" content="{q(description)}">',
        f'<link rel="canonical" href="{q(url)}">',
    ]
    if feed_url:
        head.append(
            '<link rel="alternate" type="application/atom+xml" '
            f'title="{q(title)}" href="{q(feed_url)}">'
        )
    head += [
        '<meta property="og:type" content="website">',
        f'<meta property="og:title" content="{q(title)}">',
        f'<meta property="og:description" content="{q(description)}">',
        f'<meta property="og:url" content="{q(url)}">',
        '<meta property="og:locale" content="pt_BR">',
        f'<meta property="og:site_name" content="{q(SITE_NAME)}">',
        '<meta name="twitter:card" content="summary">',
        extra_head,
        f"<style>{CSS}</style></head><body>",
    ]
    header = (
        f'<header class="site"><div class="wrap"><a class="name" href="{root}index.html">'
        f"{SITE_NAME}</a><nav>"
        f'<a href="{root}index.html">Todas as filas</a>'
        f'<a href="{root}feeds.opml" title="Assinar todas as filas de uma vez">OPML</a>'
        f'<a href="{REPO_URL}">GitHub</a></nav></div></header>'
    )
    footer = (
        f'<footer><div class="wrap"><p>{stamp}</p>'
        "<p>Dados da ANVISA (API Consultas Externas), reproduzidos sem alteração. "
        "Não substitui a consulta oficial em consultas.anvisa.gov.br.</p></div></footer>"
    )
    return (
        "".join(head)
        + header
        + f'<main class="wrap">{heading or f"<h1>{html.escape(title)}</h1>"}{body}</main>'
        + footer
        + f"<script>{JS}</script></body></html>"
    )


def json_ld(obj: dict) -> str:
    """A JSON-LD script tag; `</` is escaped so no value can close the tag."""
    return (
        '<script type="application/ld+json">'
        + json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")
        + "</script>"
    )


def xml_bytes(root: ET.Element) -> bytes:
    return b'<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(
        root, encoding="unicode"
    ).encode("utf-8")


def build_site(
    snapshots: Path,
    site: Path,
    *,
    base_url: str,
    base_tag: str,
    days: int = 30,
    notice: str | None = None,
) -> dict:
    """Write site/index.html, site/feed.xsl, site/fila/<id>.xml and site/fila/<id>.html."""
    all_days = snapshot_days(snapshots)
    window = all_days[-(days + 1) :]
    if not window:
        raise SystemExit("no snapshots to build from")
    catalog = load_catalog(snapshots)
    metas = {d: load_meta(snapshots, d) for d in window}
    base_url = base_url.rstrip("/")
    (site / "fila").mkdir(parents=True, exist_ok=True)
    (site / "feed.xsl").write_text(FEED_XSL, encoding="utf-8")

    # rolling pair of days: events per subfila per day, oldest first; only the latest queues kept
    history: dict[int, list[tuple[date, list[dict]]]] = {}
    prev: dict[int, list[dict]] | None = None
    for day in window:
        curr = load_snapshot(snapshots, day)
        if prev is not None:
            for sub, events in diff_snapshots(prev, curr).items():
                history.setdefault(sub, []).append((day, events))
        prev = curr
    latest_day, latest = window[-1], prev or {}
    for sub in latest:
        history.setdefault(sub, [(latest_day, [])])  # seen only on the latest day

    meta = metas[latest_day]
    finished = datetime.fromisoformat(meta["finished"]).strftime("%Y-%m-%d %H:%M")
    stamp = (
        f"Última coleta bem-sucedida: {finished} (horário de Brasília), "
        f"{meta['subfilas_crawled']} de {meta['subfilas_total']} subfilas, {meta['rows']} processos"
        + (f", {len(meta['failed'])} subfilas falharam" if meta["failed"] else "")
        + "."
    )
    org = {"@type": "Organization", "name": "anvisa-feeds", "url": REPO_URL}
    # e.g. "today's crawl failed": shown on every page so a stale site says so, loudly
    warn = f'<div class="box warn">{html.escape(notice)}</div>' if notice else ""

    for sub, days_events in history.items():
        name, grupo, area = describe(catalog, sub)
        title = f"{name} · {grupo} · {area}"
        newest_day = days_events[-1][0]
        entries = []
        feed_url = f"{base_url}/fila/{sub}.xml"
        for day, events in reversed(days_events):
            queue = latest.get(sub) if day == newest_day else None  # full queue only once
            entries.append(
                {
                    "id": tag_uri(base_tag, "fila", str(sub), day.isoformat()),
                    "title": f"{day.isoformat()}: {summary(events)}",
                    "updated": metas[day]["finished"],
                    "link": f"{base_url}/fila/{sub}.html",
                    "content": events_html(events, queue),
                }
            )
        (site / "fila" / f"{sub}.xml").write_bytes(
            atom_feed(
                feed_id=tag_uri(base_tag, "fila", str(sub)),
                title=f"Fila ANVISA: {title}",
                self_url=f"{base_url}/fila/{sub}.xml",
                alt_url=f"{base_url}/fila/{sub}.html",
                updated=entries[0]["updated"],
                entries=entries,
            )
        )

        n = len(latest.get(sub, []))
        area_id, grupo_id = slug(area), f"{slug(area)}--{slug(grupo)}"  # grupo names repeat
        area_href, grupo_href = f"../index.html#{area_id}", f"../index.html#{grupo_id}"
        heading = (
            '<nav class="crumbs" aria-label="Você está em">'
            f'<a href="../index.html">Filas</a><span>›</span><a href="{area_href}">'
            f'{html.escape(area)}</a><span>›</span><a href="{grupo_href}">{html.escape(grupo)}</a>'
            f"</nav><h1>{html.escape(name)}</h1>"
            f'<p class="meta"><span>{n} processos em {latest_day.isoformat()}</span>'
            f'<a class="pill" href="{sub}.xml" title="Cole este endereço no seu leitor de feeds">'
            f'Feed Atom</a><button class="pill copy" type="button" data-copy="{feed_url}" hidden>'
            "Copiar endereço do feed</button>"
            f'<a class="pill" href="{sub}.json" title="A fila de hoje em JSON">JSON</a></p>'
        )
        (site / "fila" / f"{sub}.json").write_text(
            json.dumps(
                {
                    "subfila": sub,
                    "nome": name,
                    "grupo": grupo,
                    "area": area,
                    "dia": latest_day.isoformat(),
                    "coleta": meta["finished"],
                    "pagina": f"{base_url}/fila/{sub}.html",
                    "feed": feed_url,
                    "mudancas": days_events[-1][1] if newest_day == latest_day else [],
                    "fila": latest.get(sub, []),
                },
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        body = warn + f"<h2>Mudanças em {newest_day.isoformat()}</h2>"
        events, queue_block = entries[0]["content"], ""
        if n >= FILTER_MIN_ROWS:
            # the filter sits right above the table, so split the entry content around it
            i = events.index('<table class="queue"')
            events, queue_block = events[:i], events[i:]
            queue_block = filter_box("#queue", "tbody tr", "Filtrar por processo ou assunto") + (
                queue_block
            )
        body += events + queue_block + history_html(days_events[:-1])
        description = (
            f"Fila de análise da ANVISA, {name} ({grupo}, {area}): "
            f"{n} processos em {latest_day.isoformat()}. "
            "Feed Atom com entradas, saídas e mudanças de posição diárias."
        )
        crumbs = {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Filas", "item": f"{base_url}/"},
                {
                    "@type": "ListItem",
                    "position": 2,
                    "name": area,
                    "item": f"{base_url}/index.html#{area_id}",
                },
                {
                    "@type": "ListItem",
                    "position": 3,
                    "name": grupo,
                    "item": f"{base_url}/index.html#{grupo_id}",
                },
                {"@type": "ListItem", "position": 4, "name": name},
            ],
        }
        (site / "fila" / f"{sub}.html").write_text(
            page(
                title,
                body,
                stamp=stamp,
                url=f"{base_url}/fila/{sub}.html",
                description=description,
                root="../",
                feed_url=f"{base_url}/fila/{sub}.xml",
                extra_head=json_ld(crumbs),
                heading=heading,
            ),
            encoding="utf-8",
        )

    # sitemap: the HTML pages only (feeds are not pages); lastmod is the real fetch time
    urlset = ET.Element("urlset", xmlns=SITEMAP)
    for loc in [f"{base_url}/"] + [f"{base_url}/fila/{sub}.html" for sub in sorted(history)]:
        u = ET.SubElement(urlset, "url")
        ET.SubElement(u, "loc").text = loc
        ET.SubElement(u, "lastmod").text = meta["finished"]
    (site / "sitemap.xml").write_bytes(xml_bytes(urlset))
    (site / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\nSitemap: {base_url}/sitemap.xml\n", encoding="utf-8"
    )

    # index: área → grupo → subfila
    by_area: dict[str, dict[str, list[tuple[str, int]]]] = {}
    for sub in history:
        name, grupo, area = describe(catalog, sub)
        by_area.setdefault(area, {}).setdefault(grupo, []).append((name, sub))
    index_description = (
        f"Snapshots diários das filas de análise da ANVISA: {len(history)} subfilas, "
        f"um feed Atom cada, atualizados em {latest_day.isoformat()}. "
        "Acompanhe a posição do seu processo sem cadastro."
    )
    lines = [
        warn,
        '<p class="lead">Snapshots diários das <strong>filas de análise da ANVISA</strong>, as '
        f"petições que aguardam análise, um feed Atom por subfila. {len(history)} filas; "
        f"última coleta em {latest_day.isoformat()}.</p>",
        '<div class="box"><strong>Como acompanhar seu processo.</strong> Encontre a subfila '
        "abaixo e abra a página: a fila inteira está lá, com um filtro por número de processo. "
        "Para receber as mudanças, copie o endereço do <em>feed</em> e cole no seu leitor "
        "(Feedly, Inoreader, NetNewsWire, Thunderbird…); muitos leitores filtram por texto, "
        "então filtre pelo número do processo. Para assinar todas as filas de uma vez, importe "
        'o <a href="feeds.opml">arquivo OPML</a>. Cada fila também existe em JSON '
        "(<code>fila/&lt;id&gt;.json</code>).</div>",
        '<nav class="toc" aria-label="Áreas">',
    ]
    for area in sorted(by_area):
        count = sum(len(v) for v in by_area[area].values())
        lines.append(
            f'<a href="#{slug(area)}">{html.escape(area)}<span class="n">{count}</span></a>'
        )
    lines.append("</nav>")
    lines.append(filter_box("#filas", "ul.filas li", "Filtrar subfilas por nome"))
    lines.append('<div id="filas">')
    for area in sorted(by_area):
        lines.append(f'<section id="{slug(area)}" data-group><h2>{html.escape(area)}</h2>')
        for grupo in sorted(by_area[area]):
            lines.append(
                f'<div id="{slug(area)}--{slug(grupo)}" data-group><h3>{html.escape(grupo)}</h3>'
                '<ul class="filas">'
            )
            for name, sub in sorted(by_area[area][grupo]):
                n = len(latest.get(sub, []))
                zero = " zero" if n == 0 else ""
                lines.append(
                    f'<li><span class="t"><a href="fila/{sub}.html">{html.escape(name)}</a></span>'
                    f'<span class="n{zero}">{f"{n} na fila" if n else "vazia"}</span>'
                    f'<a class="feed" href="fila/{sub}.xml" title="Feed Atom desta subfila">'
                    "feed</a></li>"
                )
            lines.append("</ul></div>")
        lines.append("</section>")
    lines.append("</div>")
    lines += [
        '<section id="faq"><h2>Perguntas frequentes</h2>',
        "<h3>Com que frequência os dados são atualizados?</h3>",
        "<p>Uma vez por dia. O horário da última coleta bem-sucedida aparece no rodapé de cada "
        "página; se ele parar de avançar, a coleta falhou e nenhuma mudança é inventada.</p>",
        "<h3>O que significam “entrou”, “saiu” e “mudou de posição”?</h3>",
        "<p>São a diferença entre o snapshot de hoje e o de ontem para aquela subfila. "
        "“Saiu da fila” quer dizer que o processo não aparece mais na fila de análise; "
        "o resultado da análise só está na consulta oficial.</p>",
        "<h3>Isto é um serviço da ANVISA?</h3>",
        f'<p>Não. É um projeto independente e de <a href="{REPO_URL}">código aberto</a> que '
        "republica os dados públicos da ANVISA sem alteração. Não substitui a consulta oficial "
        "em consultas.anvisa.gov.br.</p></section>",
    ]
    dataset = {
        "@context": "https://schema.org",
        "@type": "Dataset",
        "name": SITE_NAME,
        "description": index_description,
        "url": f"{base_url}/",
        "sameAs": REPO_URL,
        "license": "https://opensource.org/licenses/MIT",
        "isBasedOn": "https://consultas.anvisa.gov.br",
        "creator": org,
        "publisher": org,
        "inLanguage": "pt-BR",
        "keywords": ["ANVISA", "fila de análise", "petições", "regulatório", "Consultas Externas"],
        "spatialCoverage": {"@type": "Place", "name": "Brasil"},
        "temporalCoverage": f"{all_days[0].isoformat()}/..",  # first snapshot ever, not the window
        "dateModified": meta["finished"],
        "isAccessibleForFree": True,
        "distribution": [
            {
                "@type": "DataDownload",
                "encodingFormat": "text/x-opml",
                "contentUrl": f"{base_url}/feeds.opml",
            }
        ],
    }
    (site / "index.html").write_text(
        page(
            SITE_NAME,
            "".join(lines),
            stamp=stamp,
            url=f"{base_url}/",
            description=index_description,
            root="",
            extra_head=json_ld(dataset),
        ),
        encoding="utf-8",
    )

    # OPML: every feed, área → grupo → subfila, for readers that import a whole catalog
    opml = ET.Element("opml", version="2.0")
    ET.SubElement(ET.SubElement(opml, "head"), "title").text = SITE_NAME
    opml_body = ET.SubElement(opml, "body")
    for area in sorted(by_area):
        area_el = ET.SubElement(opml_body, "outline", text=area)
        for grupo in sorted(by_area[area]):
            grupo_el = ET.SubElement(area_el, "outline", text=grupo)
            for name, sub in sorted(by_area[area][grupo]):
                ET.SubElement(
                    grupo_el,
                    "outline",
                    text=f"{name} · {grupo}",
                    type="rss",
                    xmlUrl=f"{base_url}/fila/{sub}.xml",
                    htmlUrl=f"{base_url}/fila/{sub}.html",
                )
    (site / "feeds.opml").write_bytes(xml_bytes(opml))
    return {"feeds": len(history), "days": len(window), "latest": latest_day.isoformat()}
