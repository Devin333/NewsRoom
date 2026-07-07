# Paper RAG Live Answer Baseline - 2026-07-07

## Status

A real LLM-backed fixture live answer baseline and a first real-corpus live answer baseline were produced locally on 2026-07-07.

The real-corpus path is now runnable against the curated 79-pair golden set and local parsed paper artifacts. The first live answer baseline below predates the curated evidence-id remap in `455bd2fa`; use the post-remap retrieval baseline as the current evidence-alignment signal, then rerun the live answer eval to refresh answer metrics.

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

## Pre-Remap Real-Corpus Live Baseline

A real-corpus LLM-backed live answer eval was run locally on 2026-07-07 after the corpus repair and before the curated evidence-id remap in `455bd2fa`.

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

This run remains useful as proof that the live answer path can execute against the real corpus. Its retrieval/golden-alignment conclusion has been superseded by the post-remap baseline below because the golden set still pointed at stale legacy chunk ids when this run was produced.

## Post-Remap Real-Corpus Retrieval Baseline

After `455bd2fa`, the curated real golden set was rerun against the same local `.newsroom/papers` corpus in retrieval-only mode to isolate evidence alignment from LLM answer quality.

Command:

```powershell
python -m business.research.rag.cli.run_evidence_eval `
  --golden-set data/eval/golden_set.json `
  --papers-dir .newsroom/papers `
  --live-retrieval `
  --retrieval-policy paper_blind_semantic_rag_v1 `
  --output-dir .newsroom/eval/evidence-real-remapped-20260707
```

Artifacts:

- `.newsroom/eval/evidence-real-remapped-20260707/evidence_regression_report.json`
- `.newsroom/eval/evidence-real-remapped-20260707/evidence_regression_report.md`

Result summary:

- Status: `PASS`
- Corpus mode: `live_retrieval`
- Answer eval mode: `none`
- Total pairs: 79
- Expected behavior distribution: 67 `answer`, 12 `abstain`
- Parsed chunks evaluated: 16,513
- Golden-set hydration: `hydrated_pairs=67`, `locator_available_pairs=67`, `type_available_pairs=67`
- Missing golden chunks: `missing_gold_chunk_pairs=0`, `missing_gold_chunk_ids=[]`
- `retrieval.hit_at_5`: `0.403`
- `retrieval.hit_at_10`: `0.522`
- `retrieval.equivalent_hit_at_10`: `0.597`
- `retrieval.mrr`: `0.295`
- `retrieval.source_locator_coverage_at_10`: `0.970`

## Current Interpretation

The live answer evaluator is operational and can call the configured LLM path. The fixture baseline is green enough to prove the live generation/evaluation loop is wired and measurable.

The production-readiness blocker has moved. The blocker is no longer missing parsed paper artifacts, lack of a real LLM run, or stale golden evidence ids. The current deterministic retrieval baseline proves the 67 answer pairs hydrate against the regenerated corpus and now carry current source locators and evidence types.

The strongest next signal is a post-remap real-corpus live answer rerun. That run should keep the same `data/eval/golden_set.json` and `.newsroom/papers` inputs, refresh abstention and answer-success metrics, and separate remaining answer-grounding failures from retrieval ranking gaps. Thresholds should not be weakened to make this pass; the useful repair slice is now answer behavior and top-k retrieval quality after evidence alignment has been repaired.
