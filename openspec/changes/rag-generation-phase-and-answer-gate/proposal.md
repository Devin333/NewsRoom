## Why

The bounded RAG loop currently stops after returning a verified context pack. Answer generation and citation checks remain outside the loop, so unsupported or wrongly cited answer claims cannot be represented as deterministic gate failures.

## What Changes

- Add framework answer candidate models, an `AnswerWorkerPort`, and a deterministic `RAGAnswerGate`.
- Extend `BoundedRAGSessionController` with an optional generation phase controlled by `generation_policy`.
- Return `ANSWERED` or `ABSTAINED` statuses only when generation is explicitly enabled; default context-pack behavior remains unchanged.
- Add a Research `PaperAnswerWorker` adapter that projects `RAGContextPack` evidence into existing `AnswerGenerator` inputs.
- Add fake/framework/business tests for verified answers, citation integrity failures, abstention, and default-off compatibility.

## Capabilities

### New Capabilities
- `rag-generation-answer-gate`: Optional verified answer generation phase for bounded Harness RAG sessions.

### Modified Capabilities

## Impact

- Affected framework modules: `framework/harness/rag/models.py`, `policy.py`, `session.py`, new `answer_gate.py`, new `answer_worker.py`, exports.
- Affected Research modules: new `business/research/rag/adapters/answer_worker.py`.
- No endpoint behavior changes in this slice; `rag_ask` gated switch remains a later change.
- Existing sessions without `generation_policy.enabled` keep returning verified context packs.
