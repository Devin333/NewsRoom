## Design

`FeedConnector.fetch()` is split into explicit fetch and parse phases:

```text
fetch text
  -> map fetch exception to taxonomy
parse text
  -> map parse exception to parse_error
empty checks
```

The connector still returns `(items, errors)` and does not raise for expected source failures. Each mapped `SourceError.metadata` includes:

```text
phase
original_exception_type
retryable
source_health_affecting
```

HTTP status codes are bucketed into 4xx/5xx taxonomy types. Timeout-like `URLError` reasons become `fetch_timeout`; other URL/network failures become `fetch_connection_error`.

## Validation

Tests cover custom fetch exceptions, timeout, HTTP 4xx/5xx, max bytes, empty responses, empty feeds, and parse errors. A smoke run uses a real closed local port to verify live workflow metrics record a taxonomy error.
