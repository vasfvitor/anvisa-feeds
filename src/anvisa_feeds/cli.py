"""`anvisa-feeds crawl` writes today's snapshot; `anvisa-feeds build` renders the site."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import typer
from anvisa.cli import handle_errors, make_client

from .cmed import crawl as crawl_cmed
from .crawl import crawl
from .feeds import build_site

app = typer.Typer(
    no_args_is_help=True, help="ANVISA analysis queues as daily snapshots and Atom feeds."
)


@app.command("crawl")
def crawl_cmd(
    snapshots: Path = typer.Option(Path("snapshots"), help="where snapshots are written"),
    area: list[int] = typer.Option([], help="only these área ids (repeatable); default all"),
    day: datetime | None = typer.Option(
        None, formats=["%Y-%m-%d"], help="snapshot date; default today in Brasília"
    ),
    refresh_catalog: bool | None = typer.Option(
        None,
        "--refresh-catalog/--no-refresh-catalog",
        help="re-walk áreas/grupos/subfilas; default: Mondays, or when catalog.json is missing",
    ),
) -> None:
    """One request per subfila, plus the catalog walk on Mondays; throttled to the gateway."""
    with handle_errors(), make_client() as client:
        meta = crawl(
            client,
            snapshots,
            day=day.date() if day else None,
            areas=area or None,
            refresh_catalog=refresh_catalog,
            log=lambda s: typer.echo(s, err=True),
        )
    typer.echo(json.dumps(meta, ensure_ascii=False))
    if meta["subfilas_crawled"] == 0:
        raise typer.Exit(1)


@app.command("build")
def build_cmd(
    snapshots: Path = typer.Option(Path("snapshots")),
    site: Path = typer.Option(Path("site")),
    base_url: str = typer.Option("https://anvisa.feeds.abelhaninja.de", help="site URL"),
    base_tag: str = typer.Option("anvisa.feeds.abelhaninja.de,2026:feeds", help="tag authority"),
    days: int = typer.Option(30, help="how many days of history each feed carries"),
    notice: str | None = typer.Option(None, help="warning shown on every page (crawl failed)"),
    cmed_snapshots: Path = typer.Option(Path("snapshots/cmed"), help="CMED monthly snapshots"),
    cmed_months: int = typer.Option(12, help="how many months of history each CMED feed carries"),
) -> None:
    """Render index.html plus one Atom feed and one page per subfila from the snapshots, and
    the CMED pages when there are CMED snapshots."""
    result = build_site(
        snapshots,
        site,
        base_url=base_url,
        base_tag=base_tag,
        days=days,
        notice=notice,
        cmed_snapshots=cmed_snapshots,
        cmed_months=cmed_months,
    )
    typer.echo(json.dumps(result))


@app.command("crawl-cmed")
def crawl_cmed_cmd(
    snapshots: Path = typer.Option(Path("snapshots/cmed"), help="where CMED snapshots go"),
    raw_dir: Path = typer.Option(Path("raw/cmed"), help="where the month's two CSVs are kept"),
) -> None:
    """Fetch CMED's price list when it changed (two conditional GETs, no credentials) and
    write the month's snapshot. Prints the meta, or {"unchanged": true}."""
    meta = crawl_cmed(snapshots, raw_dir=raw_dir, log=lambda s: typer.echo(s, err=True))
    typer.echo(json.dumps(meta if meta else {"unchanged": True}, ensure_ascii=False))
