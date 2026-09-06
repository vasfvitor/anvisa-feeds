"""Build the static site: one Atom feed and one HTML page per subfila, plus an index.

Feeds are regenerated from the last N snapshots on every build, so an entry is one subfila on
one day, and its content lists that day's events plus the queue as it stands. Nothing is
stored besides the snapshots.
"""

from __future__ import annotations

import html
from datetime import date, datetime, time
from pathlib import Path
from xml.etree import ElementTree as ET

from . import __version__
from .crawl import BRT, load_catalog, load_meta, load_snapshot, snapshot_days
from .diff import diff_snapshots, summary

ATOM = "http://www.w3.org/2005/Atom"


def iso(day: date) -> str:
    """The moment a snapshot is considered published: 06:00 in Brasília, as RFC 3339."""
    return datetime.combine(day, time(6, 0), tzinfo=BRT).isoformat()


def tag_uri(base_tag: str, *parts: str) -> str:
    return f"tag:{base_tag}:" + "/".join(parts)


def events_html(events: list[dict], queue: list[dict]) -> str:
    out = ["<p>", html.escape(summary(events)), "</p>"]
    if events:
        out.append("<ul>")
        for e in events:
            p = html.escape(e["processo"] or "?")
            if e["row"].get("expediente"):
                p += f" (exp. {html.escape(e['row']['expediente'])})"
            if e["type"] == "entered":
                out.append(f"<li>{p}: entrou na posição {e['para']}</li>")
            elif e["type"] == "left":
                out.append(f"<li>{p}: saiu da fila (estava na posição {e['de']})</li>")
            else:
                out.append(f"<li>{p}: {e['de']} → {e['para']}</li>")
        out.append("</ul>")
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
    gen = ET.SubElement(feed, "generator", version=__version__)
    gen.text = "anvisa-feeds"
    ET.SubElement(feed, "author").append(ET.Element("name"))
    feed.find("author/name").text = "anvisa-feeds (dados: ANVISA)"
    for e in entries:
        entry = ET.SubElement(feed, "entry")
        ET.SubElement(entry, "id").text = e["id"]
        ET.SubElement(entry, "title").text = e["title"]
        ET.SubElement(entry, "updated").text = e["updated"]
        ET.SubElement(entry, "link", rel="alternate", href=e["link"])
        ET.SubElement(entry, "content", type="html").text = e["content"]
    return ET.tostring(feed, encoding="utf-8", xml_declaration=True)


def page(title: str, body: str, *, stamp: str) -> str:
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title>"
        "<style>body{font:15px/1.4 system-ui,sans-serif;max-width:60rem;margin:2rem auto;"
        "padding:0 1rem;color:#222}ol li{margin:.15rem 0}.stamp{color:#666;font-size:.9em}"
        "a{color:#0645ad}</style></head><body>"
        f"<h1>{html.escape(title)}</h1>{body}"
        f'<p class="stamp">{stamp}</p>'
        '<p class="stamp">Dados da ANVISA (API Consultas Externas), reproduzidos sem alteração. '
        "Não substitui a consulta oficial em consultas.anvisa.gov.br.</p></body></html>"
    )


def build_site(
    snapshots: Path, site: Path, *, base_url: str, base_tag: str, days: int = 30
) -> dict:
    """Write site/index.html, site/fila/<id>.xml and site/fila/<id>.html. Returns counts."""
    all_days = snapshot_days(snapshots)
    if not all_days:
        raise SystemExit("no snapshots to build from")
    window = all_days[-(days + 1) :]
    loaded = {d: load_snapshot(snapshots, d) for d in window}
    catalog = load_catalog(snapshots)
    latest = window[-1]
    meta = load_meta(snapshots, latest)
    stamp = (
        f"Última coleta bem-sucedida: {meta['finished'][:16].replace('T', ' ')} "
        "(horário de Brasília), "
        f"{meta['subfilas_crawled']} de {meta['subfilas_total']} subfilas, {meta['rows']} processos"
        + (f", {len(meta['failed'])} subfilas falharam" if meta["failed"] else "")
        + "."
    )
    base_url = base_url.rstrip("/")
    (site / "fila").mkdir(parents=True, exist_ok=True)

    # events per subfila per day, from consecutive snapshots inside the window
    per_sub: dict[int, list[tuple[date, list[dict], list[dict]]]] = {}
    for prev_day, day in zip(window, window[1:], strict=False):
        for sub, events in diff_snapshots(loaded[prev_day], loaded[day]).items():
            per_sub.setdefault(sub, []).append((day, events, loaded[day][sub]))
    for sub, queue in loaded[latest].items():  # subfilas seen only on the latest day
        per_sub.setdefault(sub, [(latest, [], queue)])

    feeds = 0
    for sub, history in per_sub.items():
        info = catalog["subfilas"].get(str(sub), {})
        name = info.get("descricao") or f"subfila {sub}"
        grupo = catalog["grupos"].get(str(info.get("grupo")), {}).get("descricao", "")
        area = catalog["areas"].get(str(info.get("area")), "")
        title = f"{name} · {grupo} · {area}".strip(" ·")
        entries = []
        for day, events, queue in sorted(history, key=lambda h: h[0], reverse=True):
            entries.append(
                {
                    "id": tag_uri(base_tag, "fila", str(sub), day.isoformat()),
                    "title": f"{day.isoformat()}: {summary(events)}",
                    "updated": iso(day),
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
        latest_day, latest_events, latest_queue = max(history, key=lambda h: h[0])
        body = (
            f'<p><a href="{sub}.xml">Feed Atom</a> · '
            '<a href="../index.html">todas as filas</a></p>'
            f"<h2>{latest_day.isoformat()}</h2>" + events_html(latest_events, latest_queue)
        )
        (site / "fila" / f"{sub}.html").write_text(page(title, body, stamp=stamp), encoding="utf-8")
        feeds += 1

    # index: área → grupo → subfila
    lines = [
        "<p>Snapshots diários da fila de análise da ANVISA, um feed por subfila. "
        f"{len(per_sub)} filas.</p>"
    ]
    by_area: dict[str, dict[str, list[tuple[int, str]]]] = {}
    for sub in per_sub:
        info = catalog["subfilas"].get(str(sub), {})
        area = catalog["areas"].get(str(info.get("area")), "?")
        grupo = catalog["grupos"].get(str(info.get("grupo")), {}).get("descricao", "?")
        by_area.setdefault(area, {}).setdefault(grupo, []).append(
            (sub, info.get("descricao") or str(sub))
        )
    for area in sorted(by_area):
        lines.append(f"<h2>{html.escape(area)}</h2>")
        for grupo in sorted(by_area[area]):
            lines.append(f"<h3>{html.escape(grupo)}</h3><ul>")
            for sub, name in sorted(by_area[area][grupo], key=lambda x: x[1]):
                n = len(loaded[latest].get(sub, []))
                lines.append(
                    f'<li><a href="fila/{sub}.html">{html.escape(name)}</a> ({n}) '
                    f'<a href="fila/{sub}.xml">feed</a></li>'
                )
            lines.append("</ul>")
    (site / "index.html").write_text(
        page("Filas de análise da ANVISA", "".join(lines), stamp=stamp), encoding="utf-8"
    )
    return {"feeds": feeds, "days": len(window), "latest": latest.isoformat()}
