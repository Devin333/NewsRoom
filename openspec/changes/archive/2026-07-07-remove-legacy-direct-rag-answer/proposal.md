# Remove Legacy Direct RAG Answer

## Why

The enterprise RAG review calls out the remaining `gated=False + generate=True` path as an interface bypass: it can generate an answer without the bounded RAG session, answer gate, citation checks, transcript, replay, metrics, tenant guard, or memory policy.

## What Changes

- Remove the legacy direct answer generator path from `PaperRagApplicationService`.
- Make `generate=True, gated=False` fail closed with a clear error.
- Remove the `paper ask --legacy-direct-answer` CLI flag.
- Update tests so generated answers are proven to use gated Harness only.

## Out Of Scope

- Removing retrieve-only paper RAG.
- Removing the `gated` service parameter from the Python call signature; it remains as a fail-closed compatibility guard for direct callers.
