## Why

`05-SOURCE_PIPELINE_TARGET_ARCHITECTURE.md` requires URL canonicalization to
remove default ports. Current canonicalization lowercases host and removes
tracking parameters, but treats `https://example.com:443/post` and
`https://example.com/post` as different URLs.

## What Changes

- Remove default `:80` from HTTP URLs.
- Remove default `:443` from HTTPS URLs.
- Preserve non-default ports.

## Out Of Scope

- Relative URL resolution.
- IDNA normalization.
- Path dot-segment normalization.
