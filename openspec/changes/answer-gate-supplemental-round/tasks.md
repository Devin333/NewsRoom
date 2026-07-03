## 1. Framework Supplemental Loop

- [x] 1.1 Import and consume answer-gate unsupported claims in the generation phase.
- [x] 1.2 Add a bounded supplemental round helper that spends replan budget and reuses planner, plan gates, retrieval execution, source verification, and context assembly.
- [x] 1.3 Reassemble and verify a refreshed context pack before retrying generation.
- [x] 1.4 Preserve safe abstention and failed gate details when claims are absent, attempts are exhausted, or supplemental retrieval cannot run.

## 2. Production Policy Wiring

- [x] 2.1 Set paper RAG answer sessions to `generation_policy={"enabled": True, "max_attempts": 2}`.

## 3. Tests And Validation

- [x] 3.1 Add generation-phase tests for supplemental success, supplemental still failing, and budget exhaustion.
- [x] 3.2 Run targeted framework RAG tests.
- [x] 3.3 Run compile, strict OpenSpec validation, smoke, full tests, and strict all-change validation.
