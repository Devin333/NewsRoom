## Why

The live answer workflow now writes readiness artifacts, but the real-corpus eval step still runs whenever `.newsroom/papers` exists. Local readiness proved that this is too weak: the directory can exist while the curated golden set references paper ids missing from the parsed corpus. Running real-corpus eval in that state can produce a misleading baseline.

## What Changes

- Add a readiness CLI gate mode for fixture and real-corpus eligibility.
- Keep plain readiness checks diagnostic and zero-exit.
- Make the workflow run real-corpus live answer eval only when readiness reports full real-corpus eligibility.
- Keep uploading readiness artifacts when real-corpus eval is skipped.

## Impact

- Affected code: `business/research/rag/evaluation/live_answer_readiness.py`, `business/research/rag/cli/check_live_answer_readiness.py`, `scripts/dev.py`.
- Affected workflow: `.github/workflows/rag-live-answer-eval.yml`.
- Affected tests: readiness CLI and workflow/dev command contract tests.
