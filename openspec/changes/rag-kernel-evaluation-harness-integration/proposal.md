## Why

The RAG kernel now has core DTOs plus retrieval/context utilities, but reusable evaluation metrics and a Harness-facing bridge are still missing. We need generic retrieval/answer scorecards and a safe adapter between `framework.rag.core.RAGEvidence` and Harness `EvidenceCandidate` before Research can stop owning all RAG evaluation and context-pack integration details.

## What Changes

- Add `framework/rag/evaluation` for generic retrieval metrics, answer metrics, failure reasons, and reports.
- Add a Harness RAG evidence adapter that converts `RAGEvidence` into `EvidenceCandidate` without importing Research code.
- Keep existing `BoundedRAGSessionController`, Research benchmark behavior, and Paper RAG scoring unchanged in this slice.
- Add tests for metrics, report output, failure reason classification, and Harness evidence conversion.

## Capabilities

### New Capabilities

- `rag-kernel-evaluation`: introduces reusable retrieval/answer metric calculators, failure reasons, and report serialization.
- `rag-harness-kernel-evidence-adapter`: introduces a Harness-owned adapter for consuming framework RAG evidence contracts.

### Modified Capabilities

- None

## Impact

Affected code includes new `framework/rag/evaluation` modules, one new Harness RAG adapter module, and focused tests. Existing Research evaluation modules keep working and can migrate to these calculators in later changes.
