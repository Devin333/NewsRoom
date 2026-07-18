## Why

The Source Pipeline target architecture requires a stable source error taxonomy. The current feed connector reports raw Python exception names for fetch and parse failures, which makes health, metrics, and operator diagnostics inconsistent.

## What Changes

- Map feed fetch failures to taxonomy error types such as `fetch_timeout`, `fetch_connection_error`, `fetch_http_4xx`, `fetch_http_5xx`, and `max_bytes_exceeded`.
- Map feed parsing failures to `parse_error`.
- Preserve original exception type and retryability metadata on `SourceError`.
- Update daily runner metrics/tests to use taxonomy error types.

## Out Of Scope

- Full robots/rate limit taxonomy.
- Per-source custom retry policies.
- Connector types beyond feed/RSS/Atom.
