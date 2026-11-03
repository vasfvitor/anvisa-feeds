"""Ritmo da fila: how many processes left each subfila per week over the last six complete weeks.

For people who follow petitions, and on purpose without a forecast date: the weekly exits of
most subfilas change too much from one week to the next for a date to mean anything, and the
page shows that variation instead. An exit is a process present one day and gone the next
(`diff.diff_queue`, same identity as the feeds). The weeks count back from the latest snapshot,
so they are the same six weeks for every subfila."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from .crawl import load_snapshot, snapshot_days
from .diff import diff_queue

WEEKS = 6
DAYS = WEEKS * 7
MIN_DAYS = 35  # below this many days with data in the 42, the subfila is "dados incompletos"
REGULAR_MIN_EXITS = 6  # at least one a week on average
REGULAR_MAX_CV = 0.5  # weekly exits within half their mean, as a spread
HEAD_MIN = 3  # an exit from position ≤ max(exits that day, 3) left from the front of the queue

SITUACOES = ("regular", "irregular", "parada", "vazia", "incompleta")
ROTULOS = {
    "regular": "regular",
    "irregular": "irregular",
    "parada": "parada",
    "vazia": "vazia",
    "incompleta": "dados incompletos",
}
PLURAIS = {
    "regular": "regulares",
    "irregular": "irregulares",
    "parada": "paradas",
    "vazia": "vazias",
    "incompleta": "com dados incompletos",
}


def contar(n: int, situacao: str) -> str:
    """ "1 parada", "44 paradas", "6 com dados incompletos": a count of subfilas in a situação."""
    if situacao == "incompleta":
        return f"{n} com dados incompletos"
    return f"{n} {ROTULOS[situacao] if n == 1 else PLURAIS[situacao]}"


@dataclass(frozen=True)
class Ritmo:
    subfila: int
    na_fila: int  # processes on the latest day the subfila was collected
    semanas: tuple[int, ...]  # exits per week, oldest first
    do_comeco: int  # exits from the front of the queue
    dias_com_dado: int  # days of the 42 covered by a diff the subfila was in, at both ends
    teve_processos: bool  # any process on any day of the window

    @property
    def saidas(self) -> int:
        return sum(self.semanas)

    @property
    def situacao(self) -> str:
        if self.dias_com_dado < MIN_DAYS:
            return "incompleta"
        if not self.teve_processos:
            return "vazia"
        if self.saidas == 0:
            return "parada"
        media = self.saidas / len(self.semanas)
        cv = statistics.pstdev(self.semanas) / media
        regular = self.saidas >= REGULAR_MIN_EXITS and cv < REGULAR_MAX_CV
        return "regular" if regular else "irregular"


def janela(snapshots: Path, ate: date | None = None) -> tuple[date, date]:
    """(first, last) day of the six weeks: last is the latest snapshot (or `ate`); a diff ending
    on first..last counts, so the day before `first` is read as the starting queue."""
    fim = ate or snapshot_days(snapshots)[-1]
    return fim - timedelta(days=DAYS - 1), fim


def medir(snapshots: Path, ate: date | None = None) -> dict[int, Ritmo]:
    """The ritmo of every subfila seen in the window. Consecutive snapshots are diffed even across
    a missing day (the exits go to the later day's week, the days in between count as covered);
    a subfila missing from either end of a diff, as on a failed crawl, gets no data for it."""
    inicio, fim = janela(snapshots, ate)
    dias = [d for d in snapshot_days(snapshots) if inicio - timedelta(days=1) <= d <= fim]
    semanas: dict[int, list[int]] = {}
    comeco: dict[int, int] = {}
    cobertos: dict[int, int] = {}
    na_fila: dict[int, int] = {}
    teve: dict[int, bool] = {}
    prev: dict[int, list[dict]] | None = None
    prev_dia: date | None = None
    for dia in dias:
        curr = load_snapshot(snapshots, dia)
        for sub, rows in curr.items():
            semanas.setdefault(sub, [0] * WEEKS)
            na_fila[sub] = len(rows)
            teve[sub] = teve.get(sub, False) or bool(rows)
        if prev is not None and prev_dia is not None:
            semana = WEEKS - 1 - (fim - dia).days // 7
            for sub in curr.keys() & prev.keys():
                saidas = [e for e in diff_queue(prev[sub], curr[sub]) if e["type"] == "left"]
                semanas[sub][semana] += len(saidas)
                limite = max(len(saidas), HEAD_MIN)
                frente = sum(1 for e in saidas if e["de"] is not None and e["de"] <= limite)
                comeco[sub] = comeco.get(sub, 0) + frente
                # the days this diff covers that fall inside the window
                cobertos[sub] = (
                    cobertos.get(sub, 0) + (dia - max(prev_dia, inicio - timedelta(1))).days
                )
        prev, prev_dia = curr, dia
    return {
        sub: Ritmo(
            subfila=sub,
            na_fila=na_fila[sub],
            semanas=tuple(semanas[sub]),
            do_comeco=comeco.get(sub, 0),
            dias_com_dado=cobertos.get(sub, 0),
            teve_processos=teve[sub],
        )
        for sub in semanas
    }
