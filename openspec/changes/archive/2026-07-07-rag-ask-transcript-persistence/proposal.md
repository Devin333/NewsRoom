## Why

Gated Paper RAG ask already returns a `transcript_id`, but the transcript itself only lives in memory. Operators cannot replay or inspect a completed `rag_ask` run by id after the request finishes, which leaves the review path incomplete for production answer failures.

## What Changes

- Persist gated `rag_ask` transcripts to `.newsroom/rag/transcripts/` after the bounded RAG session finishes.
- Add a file-backed transcript store that maps transcript ids to stable JSON artifact paths.
- Add a local `scripts.dev replay-rag <transcript-id-or-path>` command that loads a persisted transcript and runs deterministic RAG replay.
- Return the persisted transcript artifact path in the gated `rag_ask` payload for audit workflows.
- Add tests covering transcript persistence, replay loading, CLI wiring, and no-op behavior for retrieve-only requests.

## Capabilities

### New Capabilities
- `rag-ask-transcript-persistence`: Persist and replay gated Paper RAG ask transcripts by id or artifact path.

### Modified Capabilities

## Impact

- Affected code: `interfaces/services/paper_rag_service.py`, a new interface transcript store module, `scripts/dev.py`, and interface/CLI tests.
- Affected artifacts: `.newsroom/rag/transcripts/*.json` local audit files.
- No external API breaking change; the gated payload gains an additive `transcript_artifact` field.
