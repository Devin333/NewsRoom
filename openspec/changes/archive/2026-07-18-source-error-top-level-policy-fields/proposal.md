## Why

`05-SOURCE_PIPELINE_TARGET_ARCHITECTURE.md` defines `SourceError` with
top-level source identity and retry policy fields. Current errors hide
`retryable` inside metadata and omit `source_name`, which makes API, replay, and
artifact consumers infer core error policy from connector-specific metadata.

## What Changes

- Add `source_name`, top-level `retryable`, `request_ref`, and `response_ref`
  fields to `SourceError`.
- Derive `retryable` from metadata when old call sites do not set it directly.
- Populate source names from source connectors and fetch-policy helpers.
- Keep existing metadata for backward compatibility.

## Out Of Scope

- Removing legacy metadata keys.
- Adding artifact references to connector errors.
