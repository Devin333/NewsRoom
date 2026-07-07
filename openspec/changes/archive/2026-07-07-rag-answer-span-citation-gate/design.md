## Context

Harness RAG already carries span references on accepted evidence and verifies answer-level evidence ids in `RAGAnswerGate`. `AnswerClaim` currently records only `evidence_ids`, so a generated answer can pass citation integrity without proving that each claim is bound to concrete source spans.

## Goals / Non-Goals

**Goals:**
- Add claim-level span references to the framework answer candidate contract.
- Verify claim spans deterministically against the verified `RAGContextPack`.
- Keep abstention candidates valid without requiring spans.
- Preserve Paper RAG service consumers by adding span data without changing existing citation keys.

**Non-Goals:**
- Add an LLM-as-judge citation verifier.
- Infer exact character offsets from answer text.
- Change retrieval ranking, parser span extraction, or context-pack assembly.
- Introduce OpenTelemetry or cross-service observability in this slice.

## Decisions

1. Store claim spans on `AnswerClaim`.
   - Rationale: claim support belongs with the claim, not only with the answer-level citation list.
   - Alternative: add a separate `citations` model. Rejected for this slice because the existing answer candidate is small and tests already reason through claims.

2. Add a separate `rag_answer_span_citation_integrity` gate.
   - Rationale: evidence-id citation failures and span citation failures should be diagnosable independently in metrics and transcripts.
   - Alternative: fold span checks into `rag_answer_citation_integrity`. Rejected because existing metrics and tests already treat id integrity as a distinct gate.

3. Require every cited evidence id on a non-abstained claim to have at least one cited span from that same evidence.
   - Rationale: a claim that cites multiple evidence ids should not be allowed to provide a span for only one of them.
   - Alternative: require only one span per claim. Rejected because it weakens multi-evidence claim grounding.

4. Let Paper `PaperAnswerWorker` attach all verified spans for cited evidence ids.
   - Rationale: the current worker emits a conservative single claim from generated answer text. Until claim extraction becomes more granular, binding that claim to the verified spans for its cited context is the most inspectable deterministic behavior.
   - Alternative: ask the LLM to emit span ids. Rejected because this would add prompt/schema complexity and make correctness depend on model formatting.

## Risks / Trade-offs

- [Risk] Existing fake answer candidates without spans will fail the stricter gate. -> Mitigation: update tests and the Paper answer worker to produce claim spans.
- [Risk] The first version may attach broad evidence spans to a degraded single claim. -> Mitigation: the claim remains marked as degraded in metadata; later work can add structured claim extraction.
- [Risk] Downstream clients may ignore span data. -> Mitigation: expose spans additively in the existing `citations` payload.
