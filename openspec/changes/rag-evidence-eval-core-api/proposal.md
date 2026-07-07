## Why

`live_answer_eval` and `ci_eval_gate` currently call `run_evidence_eval` through the CLI module with in-process argv lists. That keeps evaluation library code coupled to CLI flag spelling and makes future evidence eval changes easier to break at runtime.

## What Changes

- Introduce a structured evidence evaluation core API that accepts an options object instead of argv strings.
- Keep the existing `run_evidence_eval` CLI behavior as a thin argparse wrapper around the core API.
- Migrate live answer evaluation and CI gate evaluation helpers to call the structured core API.
- Preserve existing helpers used by benchmark code and tests.
- Add tests proving live and CI eval callers pass structured options instead of argv lists.

## Capabilities

### New Capabilities
- `rag-evidence-eval-core-api`: Evidence evaluation exposes a structured core API for library callers while keeping the CLI compatible.

### Modified Capabilities

## Impact

- Affected code: `business/research/rag/cli/run_evidence_eval.py`, `business/research/rag/evaluation/live_answer_eval.py`, `business/research/rag/evaluation/ci_eval_gate.py`.
- Affected tests: evidence eval, live answer eval, and CI eval gate tests.
- No breaking change; existing CLI flags and command return codes remain supported.
