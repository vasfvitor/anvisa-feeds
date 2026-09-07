"""Build the static site: one Atom feed and one HTML page per subfila, plus an index.

Feeds are regenerated from the last N snapshots on every build. An entry is one subfila on
one day and lists that day's events; only the newest entry also carries the queue as it
stands, so a feed stays small however long the window. Snapshots are read one day at a time.
"""

from __future__ import annotations

import html
from datetime import date, datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from . import __version__
from .crawl import describe, load_catalog, load_meta, load_snapshot, snapshot_days
from .diff import diff_snapshots, summary

ATOM = "http://www.w3.org/2005/Atom"
CSS = (
    "body{font:15px/1.4 system-ui,sans-serif;max-width:60rem;margin:2rem auto;"
    "padding:0 1rem;color:#222}ol li{margin:.15rem 0}.stamp{color:#666;font-size:.9em}"
    "a{color:#0645ad}.box{background:#f4f6f8;border-left:4px solid #0645ad;"
    "padding:.8rem 1rem;margin:1rem 0}.entry{margin:1.5rem 0}h2{font-size:1.1em}"
)
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
<h1><xsl:value-of select="atom:feed/atom:title"/></h1>
<div class="box"><strong>Isto é um feed Atom.</strong> Para receber as mudanças desta fila, copie o
endereço desta página e cole no seu leitor de feeds (Feedly, Inoreader, NetNewsWire, Thunderbird…).
A versão para ler no navegador está em
<a><xsl:attribute name="href">
<xsl:value-of select="atom:feed/atom:link[@rel='alternate']/@href"/>
</xsl:attribute>página da fila</a>.</div>
<xsl:for-each select="atom:feed/atom:entry">
<div class="entry"><h2><xsl:value-of select="atom:title"/></h2>
<xsl:value-of select="atom:content" disable-output-escaping="yes"/></div>
</xsl:for-each>
</body></html>
</xsl:template>
</xsl:stylesheet>
"""


def tag_uri(base_tag: str, *parts: str) -> str:
    return f"tag:{base_tag}:" + "/".join(parts)


def events_html(events: list[dict], queue: list[dict] | None = None) -> str:
    """The day's events as HTML; with `queue`, the current queue after them."""
    out = ["<p>", html.escape(summary(events)), "</p>"]
    if events:
        out.append("<ul>")
        for e in events:
            p = html.escape(e["processo"] or "?")
            if e["expediente"]:
                p += f" (exp. {html.escape(e['expediente'])})"
            if e["type"] == "entered":
                out.append(f"<li>{p}: entrou na posição {e['para']}</li>")
            elif e["type"] == "left":
                out.append(f"<li>{p}: saiu da fila (estava na posição {e['de']})</li>")
            else:
                out.append(f"<li>{p}: {e['de']} → {e['para']}</li>")
        out.append("</ul>")
    if queue is not None:
        out.append(f"<p>Fila hoje ({len(queue)} processos):</p><ol>")
        for r in queue:
            out.append(
                f'<li value="{r["posicao"]}">{html.escape(r["processo"] or "")} · '
                f"{html.escape(r['dsAssunto'] or '')} · entrada {r['entrada'] or '?'}</li>"
            )
        out.append("</ol>")
    return "".join(out)


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
    # the stylesheet makes a browser show a readable page instead of raw XML; readers ignore it
    return (
        b'<?xml version="1.0" encoding="utf-8"?>\n'
        b'<?xml-stylesheet type="text/xsl" href="../feed.xsl"?>\n'
        + ET.tostring(feed, encoding="unicode").encode("utf-8")
    )


def page(title: str, body: str, *, stamp: str) -> str:
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body>"
        f"<h1>{html.escape(title)}</h1>{body}"
        f'<p class="stamp">{stamp}</p>'
        '<p class="stamp">Dados da ANVISA (API Consultas Externas), reproduzidos sem alteração. '
        "Não substitui a consulta oficial em consultas.anvisa.gov.br.</p></body></html>"
    )


def build_site(
    snapshots: Path, site: Path, *, base_url: str, base_tag: str, days: int = 30
) -> dict:
    """Write site/index.html, site/feed.xsl, site/fila/<id>.xml and site/fila/<id>.html."""
    window = snapshot_days(snapshots)[-(days + 1) :]
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

    for sub, days_events in history.items():
        name, grupo, area = describe(catalog, sub)
        title = f"{name} · {grupo} · {area}"
        newest_day = days_events[-1][0]
        entries = []
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
        body = (
            f'<p><a href="{sub}.xml">Feed Atom</a> (cole o endereço no seu leitor de feeds) · '
            '<a href="../index.html">todas as filas</a></p>'
            f"<h2>{newest_day.isoformat()}</h2>" + entries[0]["content"]
        )
        (site / "fila" / f"{sub}.html").write_text(page(title, body, stamp=stamp), encoding="utf-8")

    # index: área → grupo → subfila
    by_area: dict[str, dict[str, list[tuple[str, int]]]] = {}
    for sub in history:
        name, grupo, area = describe(catalog, sub)
        by_area.setdefault(area, {}).setdefault(grupo, []).append((name, sub))
    lines = [
        "<p>Snapshots diários da fila de análise da ANVISA, um feed por subfila. "
        f"{len(history)} filas.</p>"
    ]
    for area in sorted(by_area):
        lines.append(f"<h2>{html.escape(area)}</h2>")
        for grupo in sorted(by_area[area]):
            lines.append(f"<h3>{html.escape(grupo)}</h3><ul>")
            for name, sub in sorted(by_area[area][grupo]):
                lines.append(
                    f'<li><a href="fila/{sub}.html">{html.escape(name)}</a> '
                    f"({len(latest.get(sub, []))}) "
                    f'<a href="fila/{sub}.xml">feed</a></li>'
                )
            lines.append("</ul>")
    (site / "index.html").write_text(
        page("Filas de análise da ANVISA", "".join(lines), stamp=stamp), encoding="utf-8"
    )
    return {"feeds": len(history), "days": len(window), "latest": latest_day.isoformat()}
