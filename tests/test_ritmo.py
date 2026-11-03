"""Ritmo da fila on hand-made snapshots: one subfila per situação."""

from datetime import date, timedelta

from anvisa_feeds import ritmo
from anvisa_feeds.crawl import write_snapshot

FIM = date(2026, 11, 3)
INICIO = FIM - timedelta(days=ritmo.DAYS - 1)  # 2026-09-23


def row(n: int, pos: int) -> dict:
    return {"posicao": pos, "processo": f"P{n}", "nuProcesso": f"P{n}", "expediente": "e"}


def fila(ids: list[int]) -> list[dict]:
    return [row(n, i + 1) for i, n in enumerate(ids)]


def escrever(tmp, faltando: set[date] = frozenset()):
    """43 days (the day before the window, then 42): subfila 1 loses its head every day, 2 is
    always empty, 3 never moves, 4 moves only in one week, 5 appears 20 days before the end."""
    dia = INICIO - timedelta(days=1)
    k = 0
    while dia <= FIM:
        if dia not in faltando:
            semana = (dia - INICIO).days // 7
            quatro = list(range(400, 420))[: 20 - (10 if semana >= 3 else 0)]
            linhas = [
                {"subfila": 1, "rows": fila(list(range(k, k + 50)))},
                {"subfila": 2, "rows": []},
                {"subfila": 3, "rows": fila([300, 301, 302, 303, 304])},
                {"subfila": 4, "rows": fila(quatro)},
            ]
            if dia > FIM - timedelta(days=20):
                linhas.append({"subfila": 5, "rows": fila([500])})
            for linha in linhas:
                linha.update(area=8, grupo=0)
            write_snapshot(tmp, dia, linhas)
        dia += timedelta(days=1)
        k += 1
    return tmp


def test_each_subfila_gets_its_situacao(tmp_path):
    r = ritmo.medir(escrever(tmp_path))
    um = r[1]
    assert um.semanas == (7, 7, 7, 7, 7, 7) and um.saidas == 42 and um.do_comeco == 42
    assert um.dias_com_dado == 42 and um.na_fila == 50 and um.situacao == "regular"
    assert r[2].situacao == "vazia" and r[2].saidas == 0
    assert r[3].situacao == "parada" and r[3].na_fila == 5
    # ten leave at once in the fourth week: exits, but nothing like a rhythm
    assert r[4].semanas == (0, 0, 0, 10, 0, 0) and r[4].situacao == "irregular"
    # the ten that left all ahead of position max(10, 3)? they were positions 11..20: not the head
    assert r[4].do_comeco == 0
    assert r[5].dias_com_dado == 19 and r[5].situacao == "incompleta"


def test_a_missing_day_is_covered_by_the_diff_across_it(tmp_path):
    falta = INICIO + timedelta(days=10)
    r = ritmo.medir(escrever(tmp_path, faltando={falta}))
    # the two days' exits land on the later day; every day of the window still has data
    assert r[1].saidas == 42 and r[1].dias_com_dado == 42


def test_the_window_ends_on_the_latest_snapshot_or_on_ate(tmp_path):
    escrever(tmp_path)
    assert ritmo.janela(tmp_path) == (INICIO, FIM)
    antes = FIM - timedelta(days=7)
    assert ritmo.janela(tmp_path, antes) == (INICIO - timedelta(days=7), antes)
    # a week earlier the first week falls before the first snapshot: no data, no exits there
    r = ritmo.medir(tmp_path, antes)
    assert r[1].semanas == (0, 7, 7, 7, 7, 7) and r[1].dias_com_dado == 35
    assert r[5].dias_com_dado == 12
