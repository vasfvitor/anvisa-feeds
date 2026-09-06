"""`anvisa-feeds crawl` writes today's snapshot; `anvisa-feeds build` renders the site."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import typer
from anvisa import AnvisaError, Client, CredentialsError

from .crawl import crawl
from .feeds import build_site

app = typer.Typer(
    no_args_is_help=True, help="ANVISA analysis queues as daily snapshots and Atom feeds."
)


def make_client() -> Client:
    return Client.from_env()


@app.command("crawl")
def crawl_cmd(
    snapshots: Path = typer.Option(Path("snapshots"), help="where snapshots are written"),
    area: list[int] = typer.Option([], help="only these área ids (repeatable); default all"),
    limit: int | None = typer.Option(None, help="stop after this many subfilas (smoke tests)"),
    day: str | None = typer.Option(None, help="YYYY-MM-DD; default today in Brasília"),
) -> None:
    """One request per catalog level plus one per subfila, throttled to the gateway's rate."""
    try:
        with make_client() as client:
            meta = crawl(
                client,
                snapshots,
                day=date.fromisoformat(day) if day else None,
                areas=area or None,
                limit=limit,
                log=lambda s: typer.echo(s, err=True),
            )
    except CredentialsError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(2) from None
    except AnvisaError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from None
    typer.echo(json.dumps(meta, ensure_ascii=False))
    if meta["subfilas_crawled"] == 0:
        raise typer.Exit(1)


@app.command("build")
def build_cmd(
    snapshots: Path = typer.Option(Path("snapshots")),
    site: Path = typer.Option(Path("site")),
    base_url: str = typer.Option(
        "https://vasfvitor.github.io/anvisa-feeds", help="public URL of the site"
    ),
    base_tag: str = typer.Option(
        "vasfvitor.github.io,2026:anvisa-feeds", help="tag URI authority for feed ids"
    ),
    days: int = typer.Option(30, help="how many days of history each feed carries"),
) -> None:
    """Render index.html plus one Atom feed and one page per subfila from the snapshots."""
    result = build_site(snapshots, site, base_url=base_url, base_tag=base_tag, days=days)
    typer.echo(json.dumps(result))
