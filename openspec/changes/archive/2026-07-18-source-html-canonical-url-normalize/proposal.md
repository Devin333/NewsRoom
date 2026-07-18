## Why

HTML extraction captures canonical URLs, but canonical links can be relative or
contain tracking parameters. Source Pipeline URL normalization should apply
before the extracted URL becomes a `RawSourceItem` URL.

## What Changes

- Normalize HTML extracted canonical URLs with `canonicalize_url()`.
- Resolve relative canonical links against the source URL.
- Store the normalized canonical URL in item metadata.

## Out Of Scope

- HTML `<base href>` support.
- Fetching canonical URL targets.
- Redirect canonicalization.
