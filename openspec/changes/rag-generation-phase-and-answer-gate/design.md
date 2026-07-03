## Context

T1-T3 make retrieval verification more truthful and replanning more extensible. The next step is to bring answer generation under the same deterministic control plane without giving an LLM authority over workflow state. The LLM/answer worker drafts a candidate; the controller and gates decide whether it is acceptable.

## Goals / Non-Goals

**Goals:**
- Add an answer candidate data model with claims and cited evidence ids.
- Add deterministic answer gates for citation integrity, claim coverage, non-empty answer shape, and abstention shape.
- Keep the generation phase off by default.
- Let controller return `ANSWERED` only after answer gates pass.
- Let controller return `ABSTAINED` for valid abstention candidates or failed answer gates when generation is enabled.
- Provide a Research adapter around the existing `AnswerGenerator`.

**Non-Goals:**
- Switch `rag_ask` to the gated path.
- Add claim-level semantic LLM judging.
- Implement supplemental retrieval from unsupported claims.
- Replace existing `AnswerGenerator` prompt and repair logic.

## Decisions

1. Add `GroundedAnswerCandidate` and `AnswerClaim` in framework models.

   The model carries candidate text, explicit citations, per-claim evidence ids, and an `abstained` flag. It is a candidate, not a final decision.

2. Use pure answer gates.

   `RAGAnswerGate` checks only deterministic properties: cited ids exist in the verified context pack, claims cite at least one evidence id, answer text is non-empty unless abstained, and abstention has empty answer text.

3. Default generation policy is disabled.

   `RAGSessionSpec.generation_policy` defaults to `{}` and `RAGExecutionPolicy.generation_enabled` is false unless explicitly enabled. This preserves all existing context-pack sessions.

4. Keep T4 first version single-attempt.

   Unsupported-claim supplemental retrieval is valuable but larger. This slice exposes answer gate failures and returns `ABSTAINED` rather than silently returning an unverified answer.

5. Adapt existing `AnswerGenerator`.

   `PaperAnswerWorker` reconstructs a `RetrievalResult` from context pack evidence metadata (`paper_chunk`) when available and maps generated `context_chunk_ids` back to evidence ids. If structured claims are unavailable, it emits one conservative claim citing the generated context evidence ids.

## Risks / Trade-offs

- Degraded single-claim output is less precise than structured claim extraction. The gate still enforces citation integrity, and later work can improve prompt/schema parsing.
- Without supplemental retrieval, failed answer gates abstain instead of re-searching. That is safer than returning unsupported answers and leaves a clear next increment.
- `PaperAnswerWorker` needs chunk metadata in context pack evidence. If metadata is missing, it returns a valid abstention candidate instead of fabricating chunks.
