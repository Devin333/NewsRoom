# RAG Session Replay Design

## Scope

This change adds a read-only replay reader. It does not rerun retrieval, source verification, answer generation, or any external side effect. It consumes the transcript produced by `BoundedRAGSessionController` and reconstructs a replay report from recorded events.

## Inputs

- `RAGTranscript`
- serialized transcript dictionary
- optional fixed snapshot mapping keyed by artifact/context refs

Snapshot entries may be raw payload dictionaries or dictionaries with `payload` and `checksum`. When a checksum is present, the replay reader verifies it against a stable JSON hash of the payload.

## Output

`RAGSessionReplayResult` includes:

- transcript and session identity
- final status
- event count
- phase/event sequence
- gate result timeline
- decision timeline
- budget snapshots
- final context pack payload, if recorded
- final answer candidate payload, if recorded
- replay checks and errors

## Replayability Rules

- Empty transcripts are invalid.
- Event entries must include `event_type` and payload dictionaries.
- A terminal status must be explainable by terminal events such as `rag_context_pack_returned`, `rag_answer_returned`, `rag_abstained`, or `rag_halted`.
- When snapshots are provided, refs recorded in the final context pack must be present and pass checksum validation.

## Non-goals

- Recomputing gate results.
- Re-fetching evidence.
- Producing a diff against a new live run.
- Exposing CLI/API/MCP endpoints; generic run replay already covers interface transport.
