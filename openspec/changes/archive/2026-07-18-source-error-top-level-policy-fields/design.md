## Design

`SourceError.retryable` defaults from `metadata["retryable"]` when present, and
falls back to `True` for backward compatibility. Connectors continue to keep
the metadata key so older consumers still work.

`SourceError.to_dict()` emits the top-level fields:

- `source_name`
- `retryable`
- `request_ref`
- `response_ref`

Connector helper functions pass `source.name` when constructing errors.
