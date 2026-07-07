## Design

The CI gate already writes deterministic parsed-paper fixtures and evaluates retrieval through the real in-memory Paper RAG retriever. This change extends that gate in the smallest useful way:

1. `run_evidence_eval` receives `--deterministic-answer-eval`.
   - It converts every `EvidenceQAPair` into an `EvidenceAnswerSample`.
   - Answerable pairs use their gold facts, gold evidence ids, source locators, and supporting evidence group metadata.
   - Expected-abstain pairs use a deterministic refusal phrase recognized by the existing answer evaluator.

2. `run_ci_eval_gate` stops passing `--no-negative`.
   - Retrieval metrics remain computed over answerable samples only through existing `EvidenceRetrievalEvaluator` semantics.
   - The report metadata now proves the CI mini corpus includes both `answer` and `abstain` expected behaviors.

3. The CI gate adds answer thresholds.
   - `answer.abstention_accuracy >= 0.90`
   - `answer.success_rate >= 0.90`
   - Promotion checks also require at least one expected-abstain sample.

## Non-Goals

- Do not add network, Qdrant, Postgres, or LLM calls to PR CI.
- Do not replace full offline benchmark answer evaluation.
- Do not tune answer generation prompts or retrieval policy thresholds.
- Do not claim this is a live generated-answer benchmark; it is a deterministic PR gate for answer metric plumbing and expected-abstain regressions.
