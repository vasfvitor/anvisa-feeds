# anvisa-feeds

Daily crawl of ANVISA's queue (fila) with the `anvisa` library, published as static Atom feeds
per subfila on GitHub Pages. `README.md` explains the crawl/build/deploy split and the snapshot
format; a git-ignored `NOTES.local.md` holds pending items when present.

## Facts to keep straight

- The library lives in GitHub repo `vasfvitor/anvisa-api` (PyPI `anvisa`), not in a repo named
  `anvisa`. This repo pins it from PyPI (`pyproject.toml`, `anvisa[dados]>=0.8.0,<1`); a breaking
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
  `anvisa.dados.cmed` from the library (0.7.0 or later; 0.8.0 also refuses an unknown ICMS rate). Snapshots live in
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
- `ritmo.html` and `ritmo.json` (`ritmo.py`): exits per subfila per week over the six complete
  weeks back from the latest snapshot, read from every snapshot (not limited by `--days`), with a
  situação per subfila (regular, irregular, parada, vazia, dados incompletos) and its rule on the
  page. No forecast date on purpose; the page says why only while its own numbers back it. Each
  `fila/<id>.html` has one line about it. `meta.json` does not carry it (the hub's contract).
- Contract versions, as in the anvisa-api manifest: `schema_version` in `produtos.json`,
  `todos.json` and `substancias.json` (`cmed_dados.SCHEMA_VERSION`) and in the root `meta.json`
  (`feeds.META_SCHEMA_VERSION`), all 1. Raise one only when a reader must change to keep reading (a
  key removed, renamed or redefined), never for a new key; the portal and the hub refuse a version
  they do not know. `situacao.py` refuses an anvisa-api manifest whose `schema_version` is not 1.
- Each product in `cmed/dados` also carries `situacao` (registration Ativo/Inativo, expiry) and
  `medidas` (ANVISA measures citing the registro), read at build time from two anvisa-api Parquet
  tables (`situacao.py`, about 1.5 MB through the Pages manifest, read locally with DuckDB from
  `anvisa[dados]`). If that source fails, the build logs it and leaves both keys out; the feeds
  and prices still build. `build --anvisa-manifest ''` skips it.
- `cmed/dados/substancias.json` has the official name (DCB) of each substância, read the same way
  from `substancias_dcb` but on its own (`situacao.carregar_dcb`), so neither source takes the
  other down. It is a separate file because that table is CC BY-NC-SA 4.0, not open data: keep
  its license with it.
- Site size: the CMED pages are about 7,600 files and 100 MB (2,264 substâncias and 262
  laboratórios, each with .xml, .html and .json). The JSON carries `cmed_site.JSON_FIELDS`
  only; the full 102 columns are the `cmed` Parquet of anvisa-api.

## Public text and data on a page

This section is the same in the five health site repos (anvisa-hub, anvisa-dash, portal-saude,
anvisa-feeds, ans): a change to it goes to all five in the same round. Rules only one site needs stay
outside it. Each rule below comes from a defect found on these sites in the 2026-11-24 audit.

Data:

- Every number, date, count and name of a source comes from the data at build time. A fact that cannot
  (a phone line's hours, a legal deadline) lives in one config entry with its source link and the date it
  was checked, and the page shows both. A sentence like "nenhum número é digitado à mão" stays only
  while it holds.
- Name the source where the value is shown: the publisher and the specific file, table or page, linked.
  "Dados da ANVISA" alone is not a source. A table we derive names the publisher's files it comes from,
  never only our own script. Every page that shows, compares or ranks data has its sources, not only the
  main pages.
- A value carries the date of its copy next to it, not only in a folded section: the source's own date
  (Last-Modified, publication or list date, said as such) and our collection date where they differ.
  "Atualizado em" or "dados de" alone is ambiguous: say whose date it is. A list's file date is not the
  publisher's list date unless the data says so.
- Freshness is read from the data, never promised. No fixed sentence about cadence ("o site é refeito
  todo dia", "mostra a nova em até um dia", "nos dias úteis por volta das 12h30", "republicados
  diariamente"): say the date of the copy shown. Static output never says "hoje", "agora", "atual" or
  "vigente"; it says the date.
- A source that failed or lags is named, with the date of the copy shown and the first day it failed,
  on the pages that use it and not on the others. A producer that records failures keeps the first
  failure day across runs (it is part of the contract). When the publisher is known to be ahead of the
  copy we read (a newer list on its own page), the page says so.
- A comparison says what it compares: "coleta de 23/11 contra a de 20/11", "lista de 09/10 contra a de
  09/09". A diff that spans a missed day says so.
- Missing is said in words ("a ANS não informou o valor de março de 2026"). Null is never shown as 0,
  "nada", an empty cell, a zero-height bar or a dropped row; null, 0 and "does not apply" are separate
  branches. An unknown or new category value never falls into the reassuring branch (a value other than
  "Sim" or "Não" is "não informado", not "sem glúten"), and a company's declaration is labelled as one.
- A value the site computes (a count, rate, ranking, threshold, classification, "típica") says how, once,
  next to it or behind one link. The rule is on the page, not only in a code comment. Our own
  transformations are said: the data is "como a ANVISA publica, convertida para Parquet; entradas e
  saídas calculadas aqui", never just "sem alteração".
- A known caveat of a field is stated where the field appears (a footnote marker is explained on the
  same screen) and in the dictionary when there is one.
- The raw data (our JSON or Parquet and the publisher's file) and the data's licence are one link away
  from every page that shows it. The code licence (MIT) is never given as the data's licence, in JSON-LD
  either.
- A failure to load data in the browser is said ("não foi possível carregar as medidas"), never left
  looking like "nenhuma medida".

Writing (public text is pt-BR, for people who do not know the jargon):

- Say what the data shows and stop. No filler intro ("Aqui você encontra", "Nesta página"), no heading
  repeated by the sentence under it, no closing summary, no definition given twice on a page.
- No stock phrases or slogans: "saiba mais", "clique aqui", "tudo o que você precisa", "simples assim",
  "só fatos", "na dúvida, confira", "de forma rápida e fácil", "respostas diretas", any "sem X, sem Y"
  pair, any run of three adjectives. A link says where it goes; never "fonte" or "aqui" alone.
- No praise of the site: "transparente", "completo", "confiável", "com a fonte de cada número". A
  property of the site is said once, on its about page, and only while every page meets it. A disclaimer
  ("não substitui a consulta oficial", "sem vínculo com a ANVISA") appears once per page, in the footer,
  with the official link.
- A general claim needs the data behind it: "todos", "sempre", "nunca", "costumam", "muitas", "com
  frequência" only when the build counts it. Absence from our copy is "não está na lista da ANVISA de
  {data}", never "não está liberado no Brasil".
- Explain a term once, plainly, as to an adult: abbreviations spelled out the first time (preço fábrica
  (PF)), no English where Portuguese exists ("coletas", not "snapshots"), no analogies or wordplay, no
  reassurance or advice not asked for, no vague hedge in place of a known fact ("às vezes demora" when
  the collection has failed since a date). No emojis.
- The phrases above that a test can match are in `frases-proibidas.txt` at the repo root (identical in
  the five repos), checked over the source strings by the phrase test; a new one goes in all five lists.

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

`RUNBOOK.md` (Portuguese, for the user, not for an agent) explains every way a workflow here turns
red. Adding or changing an alarm (`::error::`, `::warning::`, an `exit 1` or a raise that ends a
workflow) or an error message means updating its entry in the same commit, quoting the message
exactly as the log prints it.
