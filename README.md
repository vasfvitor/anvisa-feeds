# anvisa-feeds

Daily snapshots of ANVISA's **filas de análise** (the queues of petitions waiting for
analysis), published as one Atom feed per subfila at
**<https://anvisa.feeds.abelhaninja.de>**. Subscribe to the feed of your subfila and
filter on your process number; no accounts, no notifications service, no server. To subscribe
to every queue at once, import `feeds.opml` into your reader.

Built on the [`anvisa`](https://pypi.org/project/anvisa/) client for ANVISA's official
Consultas Externas API. Data is ANVISA's, reproduced without alteration, and stamped with the
time of the last successful fetch. It does not replace the official consulta.

## How it works

1. A scheduled GitHub Action runs `anvisa-feeds crawl` once a day: one `fila/consulta` per
   subfila in `catalog.json`, about 314 requests at the gateway's rate of one per second. On
   Mondays it first re-walks the área, grupo and subfila catalog (about 70 more requests), so
   a new subfila is noticed within a week; `--refresh-catalog` forces that on any day.
2. The snapshot is committed under `snapshots/` as one gzipped JSON Lines file per day (one
   line per subfila), plus a `meta.json` with counts and timings and the current
   `catalog.json` of names.
3. `anvisa-feeds build` diffs consecutive days per subfila (entered, left, moved) and writes
   `site/`: `index.html`, and `fila/<id>.xml` + `fila/<id>.html` for every subfila. One feed
   entry per subfila per day; its content lists the day's events and the queue as it stands.
   Feeds carry an XSL style sheet, so a browser shows a readable page instead of raw XML.
   The root also gets `meta.json`: the latest crawl's counts and timings plus the catalog
   totals, for other sites to read.
   Every page links its feed for reader auto-discovery and carries canonical, description and
   Open Graph tags; the build also writes `sitemap.xml`, `robots.txt`, `feeds.opml`, a
   schema.org `Dataset` block on the index, and `fila/<id>.json` with each subfila's queue
   and the day's events for anyone who prefers data to HTML.
4. The site is deployed to GitHub Pages from the workflow artifact. Git history is the
   changelog.

The workflow is four jobs, crawl, cmed, build and deploy, so a rendering or deploy failure never
loses a crawl; the snapshot is also kept as a workflow artifact for 90 days in case the push
fails. If the crawl itself fails, the site is still rebuilt from the last good snapshot with a
warning on every page (`build --notice`), so staleness is visible rather than silent. "Run
workflow" with `build_only` rebuilds the site without any requests. A separate `ci` workflow
lints, tests and builds on every push and pull request.

A subfila with nothing queued answers an empty 404 and is recorded as empty. A day whose
crawl failed for a subfila produces no events for it; absence of data is not a change. Every page carries the last successful fetch time, so a broken cron shows.

## Preços CMED

The same site also carries **CMED's monthly price list** (the maximum prices of every medicine
presentation: PF, PMC and PMVG per ICMS rate), at **<https://anvisa.feeds.abelhaninja.de/cmed/>**,
as one Atom feed per substância, one per laboratório and a general one. An entry is one
month's list diffed against the previous one: what entered, what left, what changed price or
anything else. It works like the filas, with a month instead of a day:

1. `anvisa-feeds crawl-cmed` runs daily in the `cmed` job: two conditional GETs on the two
   CSVs ANVISA republishes on dados.anvisa.gov.br (`TA_PRECO_MEDICAMENTO.csv`, PF + PMC, and
   `TA_PRECO_MEDICAMENTO_GOV.csv`, PF + PMVG; no credentials). When either changed, both are
   read and merged by GGREM with `anvisa.dados.cmed` (the same code that builds the `cmed`
   Parquet of [anvisa-api](https://github.com/vasfvitor/anvisa-api)), and the month is written
   to `snapshots/cmed/<stamp>.jsonl.xz` plus `<stamp>.meta.json`, the stamp being the files'
   Last-Modified day. The raw CSVs go to the GitHub Release `cmed-<stamp>`, not to git.
2. `build` diffs consecutive months (`diff_keyed`: entered, left, changed with the fields
   that differ) and writes `site/cmed/`: `index.html` (the month's biggest PF moves, entries
   and exits, every substância and laboratório), `geral.xml`, `substancia/<slug>.{xml,html,json}`
   and `laboratorio/<cnpj>.{xml,html,json}`, `cmed.opml` and `feed.xsl`. Prices on the pages
   are PF, PMC and PMVG at ICMS 0 %; the JSON carries a short subset of columns, the Parquet
   all 102. Without CMED snapshots the build is the fila site alone.

CMED readjusts the list once a year, in March or April: that month almost every presentation
changes. The pages say so.

## Running it yourself

```bash
uv sync
export ANVISA_CLIENT_ID=... ANVISA_CLIENT_SECRET=...   # or ~/.config/anvisa/credentials.env
uv run anvisa-feeds crawl --area 8                    # a smoke test: one área
uv run anvisa-feeds crawl                             # everything
uv run anvisa-feeds crawl-cmed                        # the price list, when it changed (no credentials)
uv run anvisa-feeds build && python -m http.server -d site
uv run pytest                                          # fixture-only, no network
```

## Snapshot line

One per crawled subfila; an empty `rows` means crawled and nothing queued.

```json
{"subfila": 167, "area": 8, "grupo": 285, "rows": [
  {"posicao": 1, "processo": "25351.216322/2025-86", "nuProcesso": "25351216322202586",
   "expediente": "...", "assunto": "...", "dsAssunto": "...", "entrada": "2026-08-18"}]}
```

A CMED month (`snapshots/cmed/<stamp>.jsonl.xz`) starts with a line naming the columns, then
one JSON array per presentation in that order, the merged row of `anvisa.dados.cmed`
(`ggrem`, `registro`, `registro_produto`, substância, laboratório, the 78 prices as integer
centavos, flags as `S`/`N`, `publicado_em`):

```json
{"columns": ["ggrem", "registro", "registro_produto", "substancia", "cnpj", "laboratorio", "..."]}
["538912020009303", "1705600230032", "170560023", "21-ACETATO DE DEXAMETASONA;CLOTRIMAZOL", "18459628000115", "BAYER S.A.", "..."]
```

Not affiliated with ANVISA or CMED. MIT.
