## Design

`canonicalize_url()` now builds the netloc from parsed hostname and port instead
of using `parts.netloc` directly.

Rules:

- Lowercase hostname.
- Drop port 80 for `http`.
- Drop port 443 for `https`.
- Preserve non-default ports.
- Preserve existing query sorting and tracking-parameter removal.

IPv6 host formatting keeps brackets when the parsed hostname contains `:`.

## Compatibility

Existing canonical URLs without explicit ports are unchanged. URLs with
non-default ports remain distinct.
