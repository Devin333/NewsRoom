# Subagent Artifact Evidence And Retirement Documentation Evidence

This file records requirement-level acceptance evidence for implementation commit `3968fc17` and the final phase-27 PRD audit.

| Requirements | Accountable tasks | Implementation evidence | Test / verification evidence | Status |
| --- | --- | --- | --- | --- |
| Canonical Subagent Artifact Evidence / AST-FR-013 | 1.1..1.3, 2.1..2.4 | `ArtifactReferenceVerifierPort` is a read-only framework contract. `FilesystemHarnessArtifactPort` validates canonical ref syntax, parent-run binding, manifest identity, declared size, checksum, and bytes without returning payload or consulting publication visibility. | Adapter tests cover valid, malformed, missing, cross-run, and tampered refs. TaskPlan tests cover missing verifier, fabricated refs, valid owner, replay revalidation, zero live worker calls, and durable parent halt with no TaskResult append. | VERIFIED |
| TaskPlan Verifies Subagent Artifact References / AST-FR-006..009, AST-FR-013 | 2.1..2.4 | Acceptance and replay use the explicit verifier for every non-empty ref. Stable failures are `task_plan_subagent_artifact_verifier_required` and `task_plan_subagent_artifact_unverified`; transcript/output tuples and successful TaskResult output refs must agree. | Harness focused suite: `94 passed`. A real `SQLiteEventStore` plus `DurableTaskPlanStore` reopen test proves `TASK_PLAN_HALTED` persists and no TaskResult is committed. Offline replay does not invoke the worker again. | VERIFIED |
| Historical Agent Session Data Is Operator Owned / ASR-FR-007 | 3.1..3.2 | `docs/operations/agent-session-retirement.md` classifies the old SQLite file as orphaned historical data, forbids NewsRoom automatic access/deletion, and assigns retention/archive/removal to an explicit operator decision. | Architecture guard protects the note and proves the retired database path is absent from production source. | VERIFIED |
| Production composition | 2.3 | Research dynamic TaskPlan injects the exact production `FilesystemHarnessArtifactPort` instance into `TaskPlanResultVerifier`; no fake or string-only verifier is used. | Research artifact/composition/retirement suite: `52 passed, 2 skipped`. | VERIFIED |
| Release acceptance | 4.1..4.5 | PRD metadata, functional requirements, code impact, test plan, requirement mapping, final evidence, DoD, and maintenance guardrails reflect the live implementation and archived phase evidence. | `compile` PASS; mandatory smoke `2100 passed, 23 deselected, 22 warnings`; source validation `error_count=0`, `warning_count=0`; change strict and all-strict OpenSpec validation PASS. | VERIFIED |

## Verification Log

| Check | Result | Notes |
| --- | --- | --- |
| `./.venv/Scripts/python.exe -m pytest tests/framework/harness/task_plan tests/framework/harness/subagents tests/framework/harness/workers -q` | PASS | `94 passed in 8.45s`. |
| Research artifact/composition/retirement focused suite | PASS | `52 passed, 2 skipped in 16.28s`. |
| `./.venv/Scripts/python.exe -m scripts.dev compile` | PASS | All production package roots compiled without errors. |
| `./.venv/Scripts/python.exe -m scripts.dev smoke` | PASS | `2100 passed, 23 deselected, 22 warnings in 414.41s`; source validation reported zero errors and warnings. |
| `openspec validate close-subagent-artifact-evidence-and-retirement-docs --strict` | PASS | Corrective change is strict-valid. |
| `openspec validate --all --strict` | PASS | Every listed spec and change passed strict validation. |

## Audit Conclusion

Every phase-27 functional requirement now has a canonical owner, implementation commit, focused oracle, and durable or architectural evidence. The corrective work does not restore the retired shared-session runtime, does not give AgentRunner session ownership, and does not grant artifact publication authority to TaskPlan or subagents.
