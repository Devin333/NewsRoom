## Design

The source connector fetch policy gains:

- `rate_limit_per_domain_per_minute: int | None = None`

When unset, connector behavior remains unchanged. When set, connectors reserve a
request slot for the target URL domain before calling their fetcher. If the
domain already has too many attempts within the rolling one-minute window, the
connector returns a structured `SourceError`:

- `error_type`: `rate_limited`
- `metadata.phase`: `fetch`
- `metadata.retryable`: `true`
- `metadata.source_health_affecting`: `false`
- `metadata.domain`, `limit_per_minute`, `window_seconds`,
  `retry_after_seconds`

The limiter is in-memory and injectable so tests and workflow assembly can share
state across connector instances. It counts attempted fetches, regardless of
whether the network call succeeds.

## Compatibility

Existing policies without a rate-limit value are unchanged. Existing connector
constructors keep accepting `fetch_text` and `fetch_policy`; the new
`rate_limiter` parameter is optional.
