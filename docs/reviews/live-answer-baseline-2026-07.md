# Paper RAG Live Answer Baseline - 2026-07-07

## Status

A real LLM-backed fixture live answer baseline was produced locally on 2026-07-07.

This is the first verified live generation run for the Paper RAG answer evaluator in this worktree. It is still a fixture-corpus baseline, not a production real-corpus baseline, because the curated real golden set is not fully covered by local parsed paper artifacts yet.

## Verified Fixture Baseline

Command:

```powershell
python -m scripts.dev run-live-answer-eval `
  --output-dir .newsroom/eval/live-answer-local-20260707
```

Artifacts:

- `.newsroom/eval/live-answer-local-20260707/evidence/evidence_regression_report.json`
- `.newsroom/eval/live-answer-local-20260707/evidence/evidence_regression_report.md`
- `.newsroom/eval/live-answer-local-20260707/golden_set.json`

Result summary:

- Status: `PASS`
- Corpus mode: `fixture`
- Total pairs: 15
- Expected behavior distribution: 12 `answer`, 3 `abstain`
- Retrieval policy: `paper_blind_semantic_rag_v1`
- `answer.abstention_accuracy`: `1.000`
- `answer.success_rate`: `0.867`
- `answer.fact_coverage`: `0.833`
- `answer.citation_grounding`: `1.000`
- `answer.citation_gold_coverage`: `1.000`
- Failure taxonomy: `fact_match_low` = 2

The two answer failures were both `formula_qa` fixture cases. Negative QA behavior passed with `abstention_accuracy=1.000`.

## Real-Corpus Readiness

The curated real golden set is present:

- `data/eval/golden_set.json`
- Golden set size: 79 pairs
- Expected behavior distribution: 67 `answer`, 12 `abstain`
- Distinct paper ids in the golden set: 20

The local parsed corpus is also present:

- `.newsroom/papers`
- Parsed paper artifacts available locally after corpus repair: 88 `research_document.json` files

The real-corpus readiness gate now passes locally:

```powershell
python -m scripts.dev check-live-answer-readiness --require-real-corpus
```

Readiness artifact:

- `.newsroom/eval/live-answer-readiness/readiness.json`

Current readiness summary:

- `baseline_status`: `ready`
- Real-corpus eligibility: `true`
- Missing golden-set paper ids: 0
- Golden set: 79 pairs, 67 `answer`, 12 `abstain`, 20 distinct paper ids
- Local parsed corpus: 88 `research_document.json` files

The missing corpus coverage was repaired with:

```powershell
python -m scripts.dev ingest-golden-set-papers
```

Repair manifest:

- `.newsroom/eval/golden-set-paper-ingest-manifest.json`

Repair result:

- Requested: 12
- Succeeded: 12
- Failed: 0
- Missing after ingest: 0

The generated `.newsroom/papers` artifacts are local runtime artifacts and are not committed.

## Real-Corpus Baseline

A real-corpus LLM-backed live answer eval was run locally on 2026-07-07 after the corpus repair.

Command:

```powershell
python -m scripts.dev run-live-answer-eval `
  --golden-set data/eval/golden_set.json `
  --papers-dir .newsroom/papers `
  --output-dir .newsroom/eval/live-answer-real-20260707
```

Artifacts:

- `.newsroom/eval/live-answer-real-20260707/evidence/evidence_regression_report.json`
- `.newsroom/eval/live-answer-real-20260707/evidence/evidence_regression_report.md`

Result summary:

- Status: `FAIL`
- Corpus mode: `live_retrieval`
- Answer eval mode: `live`
- Total pairs: 79
- Expected behavior distribution: 67 `answer`, 12 `abstain`
- Parsed chunks evaluated: 16,513
- `answer.abstention_accuracy`: `0.417` below threshold `0.800`
- `answer.success_rate`: `0.329` below threshold `0.500`
- `retrieval.hit_at_5`: `0.328`
- `retrieval.hit_at_10`: `0.433`
- `retrieval.mrr`: `0.259`
- `retrieval.source_locator_coverage_at_10`: `0.000`

Failure taxonomy:

- `abstained_over_conservative`: 22
- `abstention_wrong`: 7
- `missing_gold_in_retrieval`: 24

Diagnostic tags:

- `context_missing_primary_evidence`: 46
- `true_missing_gold_in_retrieval`: 46

## Current Interpretation

The live answer evaluator is operational and can call the configured LLM path. The fixture baseline is green enough to prove the live generation/evaluation loop is wired and measurable.

The production-readiness blocker has moved. The blocker is no longer missing parsed paper artifacts or lack of a real LLM run. The first real-corpus 79-pair LLM baseline now exists, and it fails because retrieval/golden alignment and answer grounding are below threshold.

The strongest next signal is `retrieval.source_locator_coverage_at_10=0.000` together with 46 `true_missing_gold_in_retrieval` diagnostic tags. That points toward stale or mismatched golden evidence locators/chunk ids relative to the regenerated corpus, plus retrieval ranking gaps. Thresholds should not be weakened to make this pass; the failing baseline is the useful evidence for the next repair slice.
