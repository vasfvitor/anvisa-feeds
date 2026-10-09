# Structured data on the index page

One `<script type="application/ld+json">` block, emitted by `build_site` through the
`extra_head` argument of `page()`. Fila pages carry none; a 300-page site with a block per
page gains nothing and bloats every page.

## Why `Dataset`

The site is a daily-updated public dataset with a machine-readable distribution (Atom). That
is exactly what Google Dataset Search indexes, and it is a separate search surface from web
results. `WebSite` or `Organization` would add nothing a crawler cannot already infer.

## Shape

```json
{
  "@context": "https://schema.org",
  "@type": "Dataset",
  "name": "Filas de análise da ANVISA",
  "description": "<same sentence as the index meta description>",
  "url": "<base_url>/",
  "sameAs": "https://github.com/vasfvitor/anvisa-feeds",
  "license": "https://opensource.org/licenses/MIT",
  "isBasedOn": "https://consultas.anvisa.gov.br",
  "creator": {"@type": "Organization", "name": "anvisa-feeds"},
  "inLanguage": "pt-BR",
  "keywords": ["ANVISA", "fila de análise", "petições", "regulatório", "Consultas Externas"],
  "temporalCoverage": "<first snapshot day>/..",
  "dateModified": "<meta['finished'] of the latest day>",
  "isAccessibleForFree": true,
  "distribution": [
    {
      "@type": "DataDownload",
      "encodingFormat": "text/x-opml",
      "contentUrl": "<base_url>/feeds.opml"
    }
  ]
}
```

## Field rules

- `dateModified` comes from `meta["finished"]`, never build time.
- `temporalCoverage` is an ISO interval with an open end (`YYYY-MM-DD/..`); the start is the
  oldest day in the build window, which is what the feeds actually contain.
- `license` describes the site and feeds. The underlying data is ANVISA's; `isBasedOn` says so.
- Serialize with `json.dumps(obj, ensure_ascii=False)` and replace `</` with `<\/` so a value can
  never close the script tag.
- Validate at https://validator.schema.org after any change. The test suite only checks that
  the block parses as JSON and has `@type: Dataset`.
