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
