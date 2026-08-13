# Durable Subagent Transcript Evidence

This file records requirement-level acceptance evidence. Rows remain `PENDING` until the named implementation, tests, and commit have all been verified.

| Requirements | Accountable tasks | Required evidence | Status | Commit |
| --- | --- | --- | --- | --- |
| AST-FR-001..004 | 1.1..1.5, 3.1, 3.3 | model/receipt/port roundtrip, schema/checksum, explicit-store, invocation binding, durable gate tests | PENDING | PENDING |
| AST-FR-005..006 | 2.2..2.3, 3.2, 4.1..4.4, 5.2 | result/event lineage, owner-readable context/output/transcript refs, Research attempt integration | PENDING | PENDING |
| AST-FR-007..009 | 2.4, 3.4..3.5, 4.4..4.6, 5.3 | failure reasons, crash matrix, outcome reuse, zero-live-call replay | PENDING | PENDING |
| AST-FR-010..012 | 1.5, 2.1..2.4, 3.5, 4.2, 4.5..4.6, 5.4 | private/secret/size adversarial cases, restart/concurrency/tamper, bounded query, legacy fixture diagnostic | PENDING | PENDING |
| Phase A production acceptance | 5.1..5.4, 6.1..6.4 | production non-fake composition, targeted suites, compile, smoke, strict OpenSpec validation | PENDING | PENDING |

## Verification Log

| Check | Result | Notes |
| --- | --- | --- |
| `openspec validate harness-durable-subagent-transcript --strict` | PENDING | |
| Contract and focused unit tests | PENDING | |
| Durable adapter restart/concurrency/tamper tests | PENDING | |
| TaskPlan result/event/replay/recovery tests | PENDING | |
| Research dynamic TaskPlan/composition tests | PENDING | |
| `./.venv/Scripts/python.exe -m scripts.dev compile` | PENDING | |
| `./.venv/Scripts/python.exe -m scripts.dev smoke` | PENDING | |
| `openspec validate --all --strict` | PENDING | |
