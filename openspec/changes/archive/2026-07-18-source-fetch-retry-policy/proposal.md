## Why

`05-SOURCE_PIPELINE_TARGET_ARCHITECTURE.md` defines retry behavior as part of
source fetch policy, especially for temporary HTTP failures such as 429 and
5xx. Current source connectors and source fetch tools fail after a single
transient fetch exception.

## What Changes

- Extend `SourceFetchPolicy` with retry controls.
- Add a shared fetch retry helper used by connector and source tool fetch paths.
- Retry temporary fetch failures before returning a structured source error.
- Preserve the final error taxonomy while recording the number of attempts.

## Out Of Scope

- Persistent retry queues.
- Exponential backoff scheduling.
- Retrying parse or normalization errors.
