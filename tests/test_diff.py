from anvisa_feeds.diff import diff_queue, diff_snapshots, summary


def row(n, pos):
    return {"nuProcesso": f"p{n}", "processo": f"25351.{n:06d}/2025-00", "posicao": pos}


def test_entered_left_moved():
    prev = [row(1, 1), row(2, 2), row(3, 3)]
    curr = [row(2, 1), row(3, 2), row(4, 3)]
    events = diff_queue(prev, curr)
    kinds = [(e["type"], e["processo"][6:12], e.get("de"), e.get("para")) for e in events]
    assert kinds == [
        ("moved", "000002", 2, 1),
        ("moved", "000003", 3, 2),
        ("entered", "000004", None, 3),
        ("left", "000001", 1, None),
    ]
    assert summary(events) == "1 entrou, 1 saiu, 2 mudaram de posição"


def test_no_change_and_missing_subfila_yield_nothing():
    q = [row(1, 1), row(2, 2)]
    assert diff_queue(q, q) == []
    assert summary([]) == "sem mudanças"
    assert diff_snapshots({1: q, 2: q}, {1: q, 3: q}) == {1: []}
