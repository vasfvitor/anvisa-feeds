# anvisa-feeds

Daily crawl of ANVISA's queue (fila) with the `anvisa` library, published as static Atom feeds
per subfila on GitHub Pages. `README.md` explains the crawl/build/deploy split and the snapshot
format; a git-ignored `NOTES.local.md` holds pending items when present.

## Facts to keep straight

- The library lives in GitHub repo `vasfvitor/anvisa-api` (PyPI `anvisa`), not in a repo named
  `anvisa`. This repo pins it from PyPI (`pyproject.toml`, `anvisa>=0.5.0,<1`); a breaking
  rename there means a follow-up here.
- The site is served at `https://anvisa.feeds.abelhaninja.de` since 2026-10-09. The github.io
  address 301s there and nothing in this repo should handle it: the user explicitly wanted no
  redirect or backwards-compat code. `--base-url` and `base_tag` default to the new domain
  (`src/anvisa_feeds/cli.py`).
- The catalog is re-walked on Mondays only (`crawl.py`); other days cost about 314 requests.
  The API bucket (burst 25, refill 1/s) is shared per source address with the library's own
  snapshot tooling and the unauthenticated portal endpoints.
- The second feed family is CMED's monthly price list (`cmed.py`, `cmed_site.py`, pages under
  `site/cmed/`). No credentials: two conditional GETs a day on dados.anvisa.gov.br, parsed by
  `anvisa.dados.cmed` from the library (hence `anvisa>=0.7.0`). Snapshots live in
  `snapshots/cmed/<stamp>.jsonl.xz` (arrays under a `columns` line; a month is about 3 MB),
  invisible to the fila globs, which read `snapshots/*.jsonl.gz` only. The raw CSVs of a month
  go to the GitHub Release `cmed-<stamp>` (the workflow's cmed job), never to git; `raw/` is
  ignored. `base_tag` never changes: CMED feed ids are `tag:…:cmed/substancia/<slug>` and
  `tag:…:cmed/laboratorio/<cnpj>`.
- `site/cmed/dados/` (`cmed_dados.py`) is the data contract with the public portal
  (`vasfvitor/portal-saude`): `produtos.json` (index) and `produto/<registro_produto>.json` with
  the PMC of each presentation at every ICMS rate, in centavos, pharmacy presentations only
  (about 7,600 files, 15 MB), plus `todos.json` with every product in one file (13 MB), which
  is what the portal build reads (thousands of requests made GitHub Pages answer 429); the schema is `cmed_dados_schema.md`, published as
  `dados/schema.md`. A key change there needs a follow-up in the portal. Its count is kept out
  of `meta.json` on purpose (that file is anvisa-hub's contract).
- Site size: the CMED pages are about 7,600 files and 100 MB (2,264 substâncias and 262
  laboratórios, each with .xml, .html and .json). The JSON carries `cmed_site.JSON_FIELDS`
  only; the full 102 columns are the `cmed` Parquet of anvisa-api.

## SEO

The project skill `.claude/skills/feeds-seo` plus the globally installed
`addyosmani/web-quality-skills@seo` are the references. Google Search Console verification is
deliberately deferred; the agreed design, when wanted, is a `--verification-meta` option on
`build` that injects the meta tag. Off-site work (repo About and topics, link from the
anvisa-api README, community posts) is the user's.

## Workflow

Commit when a unit of work is complete, one subject per commit, no attribution trailers.
Commits are SSH-signed, so `git commit` runs outside the sandbox: keep it as the only command
on its line. Pushing, Pages settings and repository secrets are the user's.
