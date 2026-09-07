"""`anvisa-feeds crawl` writes today's snapshot; `anvisa-feeds build` renders the site."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import typer
from anvisa.cli import handle_errors, make_client

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
    base_url: str = typer.Option("https://vasfvitor.github.io/anvisa-feeds", help="site URL"),
    base_tag: str = typer.Option("vasfvitor.github.io,2026:anvisa-feeds", help="tag URI authority"),
    days: int = typer.Option(30, help="how many days of history each feed carries"),
) -> None:
    """Render index.html plus one Atom feed and one page per subfila from the snapshots."""
    result = build_site(snapshots, site, base_url=base_url, base_tag=base_tag, days=days)
    typer.echo(json.dumps(result))
