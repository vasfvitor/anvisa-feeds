# anvisa-feeds

Daily snapshots of ANVISA's **filas de análise** (the queues of petitions waiting for
analysis), published as one Atom feed per subfila. Subscribe to the feed of your subfila and
filter on your process number; no accounts, no notifications service, no server.

Built on the [`anvisa`](https://pypi.org/project/anvisa/) client for ANVISA's official
Consultas Externas API. Data is ANVISA's, reproduced without alteration, and stamped with the
time of the last successful fetch. It does not replace the official consulta.

## How it works

1. A scheduled GitHub Action runs `anvisa-feeds crawl` once a day: one request per área,
   grupo and subfila catalog, then one `fila/consulta` per subfila. A few hundred requests at
   the gateway's rate of one per second.
2. The snapshot is committed under `snapshots/` as one gzipped JSON Lines file per day, plus a
   `meta.json` with counts and timings and the current `catalog.json` of names.
3. `anvisa-feeds build` diffs consecutive days per subfila (entered, left, moved) and writes
   `site/`: `index.html`, and `fila/<id>.xml` + `fila/<id>.html` for every subfila. One feed
   entry per subfila per day; its content lists the day's events and the queue as it stands.
4. The site is deployed to GitHub Pages from the workflow artifact. Git history is the
   changelog.

A day whose crawl failed for a subfila produces no events for it; absence of data is not a
change. Every page carries the last successful fetch time, so a broken cron shows.

## Running it yourself

```bash
uv sync
export ANVISA_CLIENT_ID=... ANVISA_CLIENT_SECRET=...   # or ~/.config/anvisa/credentials.env
uv run anvisa-feeds crawl --area 8 --limit 3          # a smoke test: 3 subfilas
uv run anvisa-feeds crawl                             # everything
uv run anvisa-feeds build && python -m http.server -d site
uv run pytest                                          # fixture-only, no network
```

## Snapshot row

```json
{"area": 8, "grupo": 285, "subfila": 167, "posicao": 1, "processo": "25351.216322/2025-86",
 "nuProcesso": "25351216322202586", "expediente": "...", "assunto": "...",
 "dsAssunto": "...", "entrada": "2026-08-18"}
```

Not affiliated with ANVISA. MIT.
