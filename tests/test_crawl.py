import gzip
import json
from datetime import date

from anvisa_feeds.crawl import crawl, load_catalog, load_meta, load_snapshot, snapshot_days


def test_crawl_writes_snapshot_meta_and_catalog(client, fake_api, tmp_path):
    day = date(2026, 9, 6)
    meta = crawl(client, tmp_path, day=day, areas=[8], log=lambda s: None)

    assert meta["date"] == "2026-09-06"
    assert meta["subfilas_crawled"] == 17 and meta["subfilas_total"] == 17
    assert meta["rows"] == 40 + 35  # subfilas 167 and 161 have recorded queues; the rest are empty
    assert meta["failed"] == []
    # 1 areas + 1 grupos + 8 subfila lists + 17 consultas
    api_calls = [r for r in fake_api.requests if "/api/v1/" in r.url.path]
    assert len(api_calls) == meta["requests"] == 1 + 1 + 8 + 17

    assert snapshot_days(tmp_path) == [day]
    queues = load_snapshot(tmp_path, day)
    assert [r["posicao"] for r in queues[167]][:3] == [1, 2, 3]
    assert queues[167][0]["processo"] == "25351.216322/2025-86"
    assert queues[172] == []  # crawled, empty: present, not missing
    assert queues[167][0]["entrada"] == "2026-08-18"
    assert load_meta(tmp_path, day)["rows"] == 75
    catalog = load_catalog(tmp_path)
    assert catalog["areas"]["8"] == "Dispositivos Médicos"
    assert catalog["subfilas"]["167"]["grupo"] == 285

    with gzip.open(tmp_path / "2026-09-06.jsonl.gz", "rt", encoding="utf-8") as fh:
        first = json.loads(fh.readline())
    assert set(first) == {
        "area",
        "grupo",
        "subfila",
        "posicao",
        "processo",
        "nuProcesso",
        "expediente",
        "assunto",
        "dsAssunto",
        "entrada",
    }


def test_limit_stops_consultas_but_keeps_the_catalog(client, fake_api, tmp_path):
    meta = crawl(client, tmp_path, day=date(2026, 9, 6), areas=[8], limit=2, log=lambda s: None)
    assert meta["subfilas_crawled"] == 2
    assert meta["subfilas_total"] == 17
    consultas = [r for r in fake_api.requests if r.url.path.endswith("/fila/consulta")]
    assert len(consultas) == 2
