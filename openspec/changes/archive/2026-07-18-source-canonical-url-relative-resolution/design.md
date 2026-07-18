## Design

`canonicalize_url(url, *, base_url=None)` resolves `url` with `urljoin` only when
`base_url` is provided. The resulting URL then flows through the existing
canonicalization rules:

- lowercase scheme and host
- remove default ports
- remove fragments
- remove tracking parameters
- sort query params
- normalize trailing slash

`source.normalize_url` accepts optional `base_url` and passes it through.

## Compatibility

Existing calls without `base_url` are unchanged.
