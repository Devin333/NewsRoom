## Why

`05-SOURCE_PIPELINE_TARGET_ARCHITECTURE.md` requires HTML extraction for
official-blog fallback, release-note pages, announcement pages, and changelogs.
The current source pipeline supports RSS/Atom, arXiv, and GitHub but has no
HTML connector or extraction result model.

## What Changes

- Add `html` as a source type.
- Add a deterministic HTML extraction result model.
- Add `HtmlConnector` that fetches HTML, extracts metadata/main text, and
  returns a `RawSourceItem`.
- Preserve extraction confidence and canonical URL in source item metadata.
- Reuse the existing fetch policy, retry policy, and per-domain rate limiter.

## Out Of Scope

- JavaScript rendering.
- Trafilatura/Newspaper external dependency integration.
- Full crawler depth or link discovery.
