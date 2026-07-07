## 1. Core API

- [x] 1.1 Add `EvidenceEvalOptions` and parser-to-options conversion.
- [x] 1.2 Extract `run_evidence_eval_core(options, *, live_answer_ask=None)` while preserving CLI `main()` behavior.

## 2. Caller Migration

- [x] 2.1 Migrate `live_answer_eval.py` to construct options and call the core API.
- [x] 2.2 Migrate `ci_eval_gate.py` to construct options and call the core API.
- [x] 2.3 Keep existing helper imports used by benchmark and focused tests compatible.

## 3. Tests And Verification

- [x] 3.1 Update live answer eval tests to assert structured options instead of argv lists.
- [x] 3.2 Add or update CI eval gate coverage for the structured core call.
- [x] 3.3 Run focused pytest, compile, and `openspec validate rag-evidence-eval-core-api --strict`.
- [x] 3.4 Commit the completed change.
