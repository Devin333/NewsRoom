## Context

`run_evidence_eval.py` owns the evidence eval orchestration, argument parsing, helper functions, and report writing. `live_answer_eval.py` and `ci_eval_gate.py` import its `main()` function and build argv lists in process, so non-CLI evaluation code depends on CLI flag spelling and argparse behavior. A previous boundary fix removed the higher-level `interfaces` dependency, but this smaller direction issue remains inside `business/research/rag`.

## Goals / Non-Goals

**Goals:**
- Add a typed `EvidenceEvalOptions` object that represents the current CLI inputs.
- Add `run_evidence_eval_core(options, *, live_answer_ask=None)` for library callers.
- Keep `main(argv, *, live_answer_ask=None)` compatible by parsing args into options and delegating to the core.
- Migrate live answer eval and CI eval gate code away from argv construction.
- Keep existing benchmark imports of evidence eval helpers working.

**Non-Goals:**
- Change evidence evaluation metrics, thresholds, report schemas, or golden set generation.
- Rename or remove existing CLI flags.
- Move all helper functions out of the CLI module in this change.
- Run external LLM calls in local tests.

## Decisions

1. Keep the first core extraction in `business/research/rag/cli/run_evidence_eval.py`.
   - Rationale: most existing helper functions are already there, and moving them to a new module would create a larger migration with little immediate value.
   - Alternative: create `business/research/rag/evaluation/evidence_eval_runner.py` and move all helpers. Rejected for this change because benchmark callers import several helpers and the PRD item only requires a structured core API and removal of argv coupling.

2. Represent CLI options with a dataclass that mirrors parsed args.
   - Rationale: live and CI callers can construct explicit fields, tests can inspect options directly, and CLI compatibility remains a simple parser-to-dataclass conversion.
   - Alternative: pass dictionaries. Rejected because dictionaries make typo errors easy and do not improve readability over argv enough.

3. Preserve `live_answer_ask` injection on both CLI and core.
   - Rationale: live answer eval uses this seam to run the gated answer path without depending on interface-layer services.

## Risks / Trade-offs

- [Risk] Mirroring every CLI flag in an options dataclass can drift when new flags are added. -> Mitigation: keep parser conversion in one function and cover representative CLI and structured caller tests.
- [Risk] Keeping the core in the CLI module does not fully separate modules by name. -> Mitigation: this removes argv coupling now while avoiding a broad helper move; a later cleanup can relocate the core module without changing the options contract.
