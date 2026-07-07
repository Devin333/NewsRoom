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
- Parsed paper artifacts available locally: 76 `research_document.json` files

However, the real-corpus live answer eval is not ready because 12 golden-set paper ids are missing from `.newsroom/papers`:

- `1312.6114`
- `2002.08909`
- `2005.11401`
- `2010.11929`
- `2105.05233`
- `2111.06377`
- `2112.10752`
- `2208.03299`
- `2303.11366`
- `2304.03442`
- `2305.18290`
- `2308.08155`

The workflow now gates the real-corpus step with:

```powershell
python -m scripts.dev check-live-answer-readiness --require-real-corpus
```

On the current machine this returns non-zero and writes readiness artifacts that explain the missing corpus coverage. This prevents the workflow from emitting misleading real-corpus metrics when the parsed artifacts do not cover the curated golden set.

## Current Interpretation

The live answer evaluator is operational and can call the configured LLM path. The fixture baseline is green enough to prove the live generation/evaluation loop is wired and measurable.

Production-readiness evidence is still pending until the 12 missing real-corpus paper artifacts are restored or regenerated and the real-corpus command succeeds:

```powershell
python -m scripts.dev run-live-answer-eval `
  --golden-set data/eval/golden_set.json `
  --papers-dir .newsroom/papers `
  --output-dir .newsroom/eval/live-answer-real
```

That real-corpus report must include `answer.abstention_accuracy`, `answer.success_rate`, and failure taxonomy counts before it should be treated as the production baseline.
