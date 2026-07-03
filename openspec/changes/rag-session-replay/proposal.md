# RAG Session Replay

## Why

The enterprise RAG review notes that generic run replay exists, but RAG sessions still lack a deterministic replay interface. Operators can inspect persisted run artifacts, yet cannot load a `RAGTranscript` and replay the RAG-specific plan, execute, verify, replan, context-pack, and answer events without invoking retrieval or LLM workers.

## What Changes

- Add a framework-level RAG session replay reader under `framework/harness/rag/replay.py`.
- Replay from `RAGTranscript` or a transcript dictionary without calling retrieval, memory, tools, or LLMs.
- Extract phase sequence, gate timeline, decisions, budget snapshots, final context pack, final answer candidate, and replay checks.
- Optionally validate fixed replay snapshots/artifact refs supplied by the caller.

## Impact

- RAG failures can be replayed from transcript data for debugging and audit.
- Existing run replay remains unchanged; this change adds a RAG-specific replay layer.

## Change Id

- `rag-session-replay`: RAG transcripts can be replayed deterministically as RAG session replay reports.
