from datetime import date
from xml.etree import ElementTree as ET

from anvisa_feeds.crawl import crawl, dump_json, load_meta, load_snapshot, write_snapshot
from anvisa_feeds.feeds import build_site

ATOM = "{http://www.w3.org/2005/Atom}"


def next_day(snapshots, day, new_day):
    """Fake the next day: process 1 leaves subfila 167, everyone moves up one."""
    queues = load_snapshot(snapshots, day)
    lines = []
    for sub, rows in queues.items():
        if sub == 167:
            rows = [dict(r, posicao=r["posicao"] - 1) for r in rows if r["posicao"] != 1]
        lines.append({"subfila": sub, "area": 8, "grupo": 0, "rows": rows})
    write_snapshot(snapshots, new_day, lines)
    meta = dict(load_meta(snapshots, day), date=new_day.isoformat())
    dump_json(snapshots / f"{new_day.isoformat()}.meta.json", meta)


def test_build_site_from_two_days(client, tmp_path):
    snapshots, site = tmp_path / "snapshots", tmp_path / "site"
    crawl(client, snapshots, day=date(2026, 9, 6), areas=[8], log=lambda s: None)
    next_day(snapshots, date(2026, 9, 6), date(2026, 9, 7))

    result = build_site(snapshots, site, base_url="https://x.test/f", base_tag="x.test,2026:f")
    assert result == {"feeds": 17, "days": 2, "latest": "2026-09-07"}
    assert (site / "index.html").exists() and (site / "feed.xsl").exists()

    raw = (site / "fila" / "167.xml").read_bytes()
    assert b'<?xml-stylesheet type="text/xsl" href="../feed.xsl"?>' in raw[:200]
    feed = ET.fromstring(raw)
    assert feed.find(f"{ATOM}id").text == "tag:x.test,2026:f:fila/167"
    entries = feed.findall(f"{ATOM}entry")
    assert [e.find(f"{ATOM}title").text for e in entries] == [
        "2026-09-07: 1 saiu, 39 mudaram de posição"
    ]
    content = entries[0].find(f"{ATOM}content").text
    assert "25351.216322/2025-86 (exp. " in content
    assert ": saiu da fila (estava na posição 1)" in content
    assert "Fila hoje (39 processos)" in content  # the newest entry carries the queue
    finished = load_meta(snapshots, date(2026, 9, 7))["finished"]
    assert entries[0].find(f"{ATOM}updated").text == finished

    page = (site / "fila" / "167.html").read_text(encoding="utf-8")
    assert "Última coleta bem-sucedida" in page and "17 de 17 subfilas" in page
    index = (site / "index.html").read_text(encoding="utf-8")
    assert "Dispositivos Médicos" in index and 'href="fila/167.xml"' in index


def test_only_the_newest_entry_carries_the_queue(client, tmp_path):
    snapshots, site = tmp_path / "snapshots", tmp_path / "site"
    crawl(client, snapshots, day=date(2026, 9, 6), areas=[8], log=lambda s: None)
    next_day(snapshots, date(2026, 9, 6), date(2026, 9, 7))
    next_day(snapshots, date(2026, 9, 7), date(2026, 9, 8))
    build_site(snapshots, site, base_url="https://x.test/f", base_tag="x.test,2026:f")

    entries = ET.parse(site / "fila" / "167.xml").getroot().findall(f"{ATOM}entry")
    contents = [e.find(f"{ATOM}content").text for e in entries]
    assert [c.count("Fila hoje") for c in contents] == [1, 0]
    assert contents[1].startswith("<p>1 saiu, 39 mudaram de posição</p>")  # the 06→07 diff
