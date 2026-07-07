## Context

`data/eval/golden_set.json` currently stores legacy rows with `question`, `source_chunk_id`, `paper_id`, and `domain`. `EvidenceQAPair.from_dict()` can load this format by mapping `source_chunk_id` to `gold_chunk_ids` and defaulting missing `expected_behavior` to `answer`.

The current risk is not loader compatibility; it is benchmark semantics. With zero real-corpus abstain rows, abstention metrics on the repository golden set cannot measure wrong-answer abstention or over-conservative abstention behavior. Separately, `data/eval/build_golden_set.py` still imports removed legacy symbols from `business.research.rag.eval`, so the documented rebuild path is broken.

## Goals / Non-Goals

**Goals:**
- Preserve legacy row readability while adding explicit `expected_behavior` labels.
- Add curated `abstain` rows that require the system to decline questions outside each paper's evidence.
- Move the rebuild script to the current `EvidenceGoldenSetBuilder` and `save_evidence_golden_set` APIs.
- Add tests for repository-level behavior counts.

**Non-Goals:**
- Do not run live LLM generation in PR checks.
- Do not rebuild all 67 answer rows into the full `EvidenceQAPair.to_dict()` shape in this slice.
- Do not implement live answer evaluation; that belongs to a separate change.

## Decisions

- Keep existing answer rows in the compact legacy-compatible shape and add `expected_behavior: "answer"`.
  - Rationale: this avoids noisy data churn while making behavior explicit.
  - Alternative considered: rewrite all rows through `EvidenceQAPair.to_dict()`. That would be valid but would obscure the small semantic change.
- Add curated negative rows with no `source_chunk_id`.
  - Rationale: `EvidenceQAPair.negative()` has no gold chunks by design, and the loader already supports abstain rows without evidence IDs.
  - Alternative considered: generate negatives mechanically from current papers. That is useful for rebuilds, but repository data should remain human-reviewable.
- Keep the builder script as an operational rebuild tool.
  - Rationale: it depends on local storage and parsed corpus state, so tests should cover importability and parser behavior without requiring Qdrant or LLM access.

## Risks / Trade-offs

- Curated negative questions may drift as the corpus changes. Mitigation: keep metadata marking them as curated and preserve domain/paper IDs for manual review.
- Compact answer rows and full abstain rows have different optional fields. Mitigation: `EvidenceQAPair.from_dict()` is the canonical compatibility boundary and tests load the repository file through it.
