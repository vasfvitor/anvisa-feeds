import gzip
import json
from datetime import date

from anvisa_feeds.crawl import (
    crawl,
    describe,
    load_catalog,
    load_meta,
    load_snapshot,
    snapshot_days,
)


def test_crawl_writes_snapshot_meta_and_catalog(client, fake_api, tmp_path):
    day = date(2026, 9, 6)  # a Sunday, but there is no catalog yet, so it is walked
    meta = crawl(client, tmp_path, day=day, areas=[8], log=lambda s: None)

    assert meta["date"] == "2026-09-06" and meta["catalog_refreshed"] is True
    # área 8 has grupos 285 (13 subfilas) and 281 (4); the other six have none
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
    assert queues[167][0]["entrada"] == "2026-08-18"
    assert queues[172] == []  # crawled, empty: present, not missing
    assert load_meta(tmp_path, day)["rows"] == 75
    catalog = load_catalog(tmp_path)
    assert catalog["areas"]["8"] == "Dispositivos Médicos"
    assert catalog["subfilas"]["167"]["grupo"] == 285
    assert describe(catalog, 167) == (
        "Alterações de Notificações de Equipamentos Classe I",
        "Alterações",
        "Dispositivos Médicos",
    )
    assert describe(catalog, 999) == ("subfila 999", "?", "?")

    with gzip.open(tmp_path / "2026-09-06.jsonl.gz", "rt", encoding="utf-8") as fh:
        first = json.loads(fh.readline())
    assert set(first) == {"subfila", "area", "grupo", "rows"}
    assert set(first["rows"][0]) == {
        "posicao",
        "processo",
        "nuProcesso",
        "expediente",
        "assunto",
        "dsAssunto",
        "entrada",
    }


def test_weekdays_reuse_the_catalog_and_mondays_walk_it(client, fake_api, tmp_path):
    crawl(client, tmp_path, day=date(2026, 9, 6), areas=[8], log=lambda s: None)
    fake_api.requests.clear()

    tuesday = crawl(client, tmp_path, day=date(2026, 9, 8), areas=[8], log=lambda s: None)
    assert tuesday["catalog_refreshed"] is False
    assert tuesday["requests"] == 17 == tuesday["subfilas_crawled"]
    api_calls = [r.url.path for r in fake_api.requests if "/api/v1/" in r.url.path]
    assert all(p.endswith("/fila/consulta") for p in api_calls) and len(api_calls) == 17
    assert load_snapshot(tmp_path, date(2026, 9, 8))[167][0]["processo"] == "25351.216322/2025-86"

    fake_api.requests.clear()
    monday = crawl(client, tmp_path, day=date(2026, 9, 7), areas=[8], log=lambda s: None)
    assert monday["catalog_refreshed"] is True and monday["requests"] == 1 + 1 + 8 + 17

    forced = crawl(
        client, tmp_path, day=date(2026, 9, 9), areas=[8], refresh_catalog=True, log=lambda s: None
    )
    assert forced["catalog_refreshed"] is True
