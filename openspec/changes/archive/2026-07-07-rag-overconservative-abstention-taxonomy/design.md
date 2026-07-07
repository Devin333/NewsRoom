## Context

Paper RAG evaluation already records answer failures and aggregates `failure_reasons` into benchmark reports and fix manifests. The current taxonomy uses `abstention_wrong` for abstention-related answer failures, but the enterprise RAG review calls out a separate operational question: is the system failing because it answered when it should abstain, or because it abstained when answerable evidence was available?

## Goals / Non-Goals

**Goals:**

- Classify expected-answer samples that produce an abstention as `abstained_over_conservative`.
- Keep `abstention_wrong` for expected-abstain samples that produce answer text.
- Preserve existing report and manifest shapes while adding the new reason wherever failure reasons are already surfaced.
- Add focused tests that prevent the two abstention failure modes from collapsing again.

**Non-Goals:**

- No prompt, retrieval, answer gate, or generation behavior changes.
- No new CI command, storage schema, or external dependency.
- No change to the numeric abstention accuracy calculation.

## Decisions

1. Add the split in the answer failure reason classifier.
   - Rationale: the classifier already has access to the per-sample expected behavior and answer score payload, so it is the narrowest ownership point.
   - Alternative: post-process aggregated reports. Rejected because fix manifests and per-sample issue details need the specific reason before aggregation.

2. Keep the existing suggested action as `fix_answer_prompt`.
   - Rationale: both over-conservative abstention and wrong answering are answer-policy failures. The new reason improves diagnosis without creating a premature remediation workflow.
   - Alternative: add a new action such as `tune_supplemental_retrieval`. Rejected for this slice because supplemental retrieval tuning is broader than failure taxonomy.

3. Preserve existing `abstention_wrong` semantics for expected-abstain misses.
   - Rationale: existing dashboards/tests may already use that reason to find unsafe non-abstention behavior. The new reason should not rename that existing signal.

## Risks / Trade-offs

- [Risk] Existing reports that filter only `abstention_wrong` may not count over-conservative abstention after this change. -> Mitigation: preserve the old reason for unsafe expected-abstain failures and add tests documenting the split.
- [Risk] Over-conservative abstention can also be caused by retrieval gaps. -> Mitigation: this change classifies the answer outcome only; retrieval failure reasons remain separately reported by evidence metrics.
