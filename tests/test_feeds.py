import json
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
    assert "<code>25351.216322/2025-86</code> <small>exp. " in content
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


def test_discoverability_files_and_head_tags(client, tmp_path):
    snapshots, site = tmp_path / "snapshots", tmp_path / "site"
    crawl(client, snapshots, day=date(2026, 9, 6), areas=[8], log=lambda s: None)
    next_day(snapshots, date(2026, 9, 6), date(2026, 9, 7))
    result = build_site(snapshots, site, base_url="https://x.test/f/", base_tag="x.test,2026:f")
    finished = load_meta(snapshots, date(2026, 9, 7))["finished"]

    assert (site / "robots.txt").read_text() == (
        "User-agent: *\nAllow: /\nSitemap: https://x.test/f/sitemap.xml\n"
    )

    sm = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
    urls = ET.parse(site / "sitemap.xml").getroot().findall(f"{sm}url")
    assert len(urls) == result["feeds"] + 1  # index + one page per feed
    locs = [u.find(f"{sm}loc").text for u in urls]
    assert locs[0] == "https://x.test/f/" and "https://x.test/f/fila/167.html" in locs
    assert not any(loc.endswith(".xml") for loc in locs)
    assert {u.find(f"{sm}lastmod").text for u in urls} == {finished}

    opml = ET.parse(site / "feeds.opml").getroot()
    rss = opml.findall(".//outline[@type='rss']")
    assert len(rss) == result["feeds"]
    (o167,) = [o for o in rss if o.get("xmlUrl") == "https://x.test/f/fila/167.xml"]
    assert o167.get("htmlUrl") == "https://x.test/f/fila/167.html"

    page = (site / "fila" / "167.html").read_text(encoding="utf-8")
    head = page.split("<body>")[0]
    assert '<link rel="canonical" href="https://x.test/f/fila/167.html">' in head
    assert (
        '<link rel="alternate" type="application/atom+xml" title="' in head
        and 'href="https://x.test/f/fila/167.xml">' in head
    )
    assert '<meta name="description" content="Fila de análise da ANVISA, ' in head
    assert "39 processos em 2026-09-07" in head
    assert '<meta property="og:url" content="https://x.test/f/fila/167.html">' in head
    crumbs = json.loads(head.split('<script type="application/ld+json">')[1].split("</script>")[0])
    assert crumbs["@type"] == "BreadcrumbList"
    assert [i["name"] for i in crumbs["itemListElement"]][1:3] == [
        "Dispositivos Médicos",
        "Alterações",
    ]
    assert (
        crumbs["itemListElement"][2]["item"]
        == "https://x.test/f/index.html#dispositivos-medicos--alteracoes"
    )

    index = (site / "index.html").read_text(encoding="utf-8")
    assert '<link rel="canonical" href="https://x.test/f/">' in index
    assert 'href="feeds.opml"' in index and "Perguntas frequentes" in index
    start = index.index('<script type="application/ld+json">') + len(
        '<script type="application/ld+json">'
    )
    ld = json.loads(index[start : index.index("</script>", start)])
    assert ld["@type"] == "Dataset" and ld["dateModified"] == finished
    assert ld["temporalCoverage"] == "2026-09-06/.."  # first snapshot ever
    assert ld["spatialCoverage"]["name"] == "Brasil" and ld["publisher"]["name"] == "anvisa-feeds"
    assert ld["distribution"][0]["contentUrl"] == "https://x.test/f/feeds.opml"


def test_json_per_subfila_and_notice(client, tmp_path):
    snapshots, site = tmp_path / "snapshots", tmp_path / "site"
    crawl(client, snapshots, day=date(2026, 9, 6), areas=[8], log=lambda s: None)
    next_day(snapshots, date(2026, 9, 6), date(2026, 9, 7))
    build_site(
        snapshots, site, base_url="https://x.test/f", base_tag="x.test,2026:f", notice="PAROU"
    )
    data = json.loads((site / "fila" / "167.json").read_text(encoding="utf-8"))
    assert data["subfila"] == 167 and data["dia"] == "2026-09-07"
    assert len(data["fila"]) == 39 and data["fila"][0]["posicao"] == 1
    assert [e["type"] for e in data["mudancas"]].count("left") == 1
    assert data["feed"] == "https://x.test/f/fila/167.xml"
    for name in ("index.html", "fila/167.html"):
        assert '<div class="box warn">PAROU</div>' in (site / name).read_text(encoding="utf-8")
    assert 'href="167.json"' in (site / "fila" / "167.html").read_text(encoding="utf-8")
