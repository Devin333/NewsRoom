## Why

`WorkerRAGPlanner` already exists but is not wired into the Paper RAG production path. Replanning therefore remains deterministic string expansion even after verification exposes missing or rejected evidence.

## What Changes

- Extend `RAGPlanner.plan()` to accept executed query history while preserving default compatibility.
- Add a `min_round_index` gate to `WorkerRAGPlanner` so the first round can stay deterministic and worker planning starts only on replans.
- Add a Research adapter that wraps `ResearchCandidateWorkerPort.generate_candidate()` into the worker result shape expected by `WorkerRAGPlanner`.
- Allow `PaperRAGSession` to optionally receive a plan worker and wire `WorkerRAGPlanner` into `BoundedRAGSessionController`.
- Preserve default deterministic planning when no plan worker is supplied.

## Capabilities

### New Capabilities
- `rag-worker-planner-wiring`: Optional worker-generated retrieval plan candidates for verified RAG replanning.

### Modified Capabilities

## Impact

- Affected framework modules: `framework/harness/rag/planner.py`, `framework/harness/rag/session.py`.
- Affected Research modules: new `business/research/rag/adapters/plan_worker.py`, updated `PaperRAGSession`.
- Affected interface composition: `build_paper_rag_session()` accepts optional plan worker injection.
- LLM/worker output remains candidate-only; existing plan gates still decide execution.
