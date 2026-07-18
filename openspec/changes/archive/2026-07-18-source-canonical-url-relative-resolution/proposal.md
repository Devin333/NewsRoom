## Why

`05-SOURCE_PIPELINE_TARGET_ARCHITECTURE.md` requires URL canonicalization to
resolve relative URLs. Current canonicalization only handles already absolute
URLs, so relative links extracted from HTML cannot be normalized against their
source page.

## What Changes

- Add optional `base_url` support to `canonicalize_url`.
- Expose optional `base_url` in `source.normalize_url`.
- Preserve existing one-argument behavior.

## Out Of Scope

- Fetching base documents.
- HTML `<base href>` parsing.
- Full RFC path dot-segment custom implementation beyond `urljoin`.
