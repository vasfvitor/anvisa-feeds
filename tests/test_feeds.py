import gzip
import json
from datetime import date
from xml.etree import ElementTree as ET

from anvisa_feeds.crawl import crawl
from anvisa_feeds.feeds import build_site

ATOM = "{http://www.w3.org/2005/Atom}"


def shift_queue(snapshots, day, new_day):
    """Fake the next day: process 1 leaves subfila 167, everyone moves up one."""
    rows = []
    with gzip.open(snapshots / f"{day}.jsonl.gz", "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            if r["subfila"] == 167:
                if r["posicao"] == 1:
                    continue
                r["posicao"] -= 1
            rows.append(r)
    with gzip.open(snapshots / f"{new_day}.jsonl.gz", "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    meta = json.loads((snapshots / f"{day}.meta.json").read_text())
    meta["date"] = new_day
    (snapshots / f"{new_day}.meta.json").write_text(json.dumps(meta))


def test_build_site_from_two_days(client, tmp_path):
    snapshots, site = tmp_path / "snapshots", tmp_path / "site"
    crawl(client, snapshots, day=date(2026, 9, 6), areas=[8], log=lambda s: None)
    shift_queue(snapshots, "2026-09-06", "2026-09-07")

    result = build_site(snapshots, site, base_url="https://x.test/f", base_tag="x.test,2026:f")
    assert result == {"feeds": 17, "days": 2, "latest": "2026-09-07"}
    assert (site / "index.html").exists()

    feed = ET.parse(site / "fila" / "167.xml").getroot()
    assert feed.find(f"{ATOM}id").text == "tag:x.test,2026:f:fila/167"
    entries = feed.findall(f"{ATOM}entry")
    assert [e.find(f"{ATOM}title").text for e in entries] == [
        "2026-09-07: 1 saiu, 39 mudaram de posição"
    ]
    content = entries[0].find(f"{ATOM}content").text
    assert "25351.216322/2025-86 (exp. " in content
    assert ": saiu da fila (estava na posição 1)" in content
    assert "Fila hoje (39 processos)" in content
    assert entries[0].find(f"{ATOM}updated").text == "2026-09-07T06:00:00-03:00"

    page = (site / "fila" / "167.html").read_text(encoding="utf-8")
    assert "Última coleta bem-sucedida" in page and "17 de 17 subfilas" in page
    index = (site / "index.html").read_text(encoding="utf-8")
    assert "Dispositivos Médicos" in index and 'href="fila/167.xml"' in index
