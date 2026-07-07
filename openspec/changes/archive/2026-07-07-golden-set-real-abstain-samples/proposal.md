## Why

The repository golden set in `data/eval/golden_set.json` is real-corpus evidence, but it only contains answerable rows and lacks explicit `expected_behavior` labels. That makes abstention metrics meaningful only on generated CI fixtures, not on the reusable real-corpus benchmark.

## What Changes

- Add explicit answer/abstain behavior labels to the repository golden set.
- Add real-corpus abstain negative samples that cover the existing domains.
- Repair the golden set build entrypoint so future rebuilds use the current evidence-evaluation model and can include negative samples.
- Add regression coverage that fails when the repository golden set has no abstain samples.

## Capabilities

### New Capabilities
- `rag-real-golden-set-evaluation`: Real-corpus RAG golden sets carry behavior labels and include answerable plus abstain samples for evaluation.

### Modified Capabilities

## Impact

- Affects `data/eval/golden_set.json`, `data/eval/build_golden_set.py`, and RAG evaluation tests.
- No API or storage migration is required.
