## Design

`SourceFetchPolicy` gains:

- `retry_times: int = 2`
- `retry_on_status_codes: tuple[int, ...] = (429, 500, 502, 503, 504)`

Connectors and source tools wrap only the fetch operation with
`run_with_fetch_retries()`. Parse failures, empty responses, max-byte failures,
and invalid source configuration are not retried.

Retryable cases:

- HTTP errors whose status code is configured in `retry_on_status_codes`
- timeout errors
- URL/network connection errors
- unknown fetch exceptions from an injected fetcher

The helper re-raises the final exception and annotates it with
`source_fetch_attempts`, allowing existing error taxonomy code to keep returning
`fetch_http_5xx`, `fetch_timeout`, or `fetch_connection_error` while adding
attempt metadata.

## Compatibility

Existing constructors are unchanged. Callers that need previous one-shot
behavior can set `retry_times=0`.
