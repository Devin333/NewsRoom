# Durable Subagent Transcript Evidence

This file records requirement-level acceptance evidence for implementation commit `db3fda0c`.

| Requirements | Accountable tasks | Required evidence | Status | Commit |
| --- | --- | --- | --- | --- |
| AST-FR-001..004 | 1.1..1.5, 3.1, 3.3 | Versioned model/receipt/port roundtrip, exact schema/checksum, explicit store injection, invocation binding, and read-back gate tests passed in the 160-test focused suite. | VERIFIED | `db3fda0c` |
| AST-FR-005..006 | 2.2..2.3, 3.2, 4.1..4.4, 5.2 | Context/output/transcript bundle refs resolve after reopen; success/failure TaskResult and terminal event lineage plus all three Research roles passed. | VERIFIED | `db3fda0c` |
| AST-FR-007..009 | 2.4, 3.4..3.5, 4.4..4.6, 5.3 | Atomic result-event failure matrix, post-receipt recovery, zero-worker committed-outcome reuse, and offline replay call-count tests passed. | VERIFIED | `db3fda0c` |
| AST-FR-010..012 | 1.5, 2.1..2.4, 3.5, 4.2, 4.5..4.6, 5.4 | Private/secret/size rejection, Windows process concurrency, restart/tamper/query bounds, production source boundaries, and exact legacy-unavailable diagnostics passed. | VERIFIED | `db3fda0c` |
| Phase A production acceptance | 5.1..5.4, 6.1..6.4 | Production Research composition uses the filesystem adapter with no implicit fake; focused, compile, smoke, source validation, and strict OpenSpec gates passed. | VERIFIED | `db3fda0c` |

## Verification Log

| Check | Result | Notes |
| --- | --- | --- |
| `openspec validate harness-durable-subagent-transcript --strict` | PASS | Change is valid. |
| Contract and focused unit tests | PASS | Aggregate focused command: `160 passed in 20.24s`. |
| Durable adapter restart/concurrency/tamper tests | PASS | Included reopen, two-instance/thread/process, immutable conflict, tamper, missing body, limits, scoped query, and unavailable-root cases. |
| TaskPlan result/event/replay/recovery tests | PASS | Included success/failure lineage, v1 migration, atomic result/terminal batch failure, post-receipt recovery, tamper, and zero-live-call replay. |
| Research dynamic TaskPlan/composition tests | PASS | Included all three production roles, filesystem reopen, offline replay, unavailable runtime, and post-receipt crash reuse. |
| `./.venv/Scripts/python.exe -m scripts.dev compile` | PASS | `compileall` completed for `business`, `framework`, `infrastructure`, `interfaces`, and `scripts`. |
| `./.venv/Scripts/python.exe -m scripts.dev smoke` | PASS | `2090 passed, 23 deselected`; source validation reported `error_count=0`, `warning_count=0`. |
| `openspec validate --all --strict` | PASS | `525 passed, 0 failed`. |
