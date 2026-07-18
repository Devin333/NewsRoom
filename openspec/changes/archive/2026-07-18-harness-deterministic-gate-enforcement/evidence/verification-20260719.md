# Verification Evidence - 2026-07-19

## Candidate Identity

- Change: `harness-deterministic-gate-enforcement`
- Schema: `spec-driven`
- Base commit: `e1cd72f372e8df0d745de35b93021c1315f23d67`
- Tested staged candidate: `df7972e3838affb372ad2db21fb39c0251d89d7f`
- Candidate construction: `git write-tree`, `git commit-tree`, then a detached `git worktree add`
- Candidate delta: 52 files relative to the base commit
- Python: `3.14.4`
- OpenSpec CLI: `1.3.1`

The candidate was built only from the main worktree index. Unstaged and untracked
parallel changes under Tool, Redis, interfaces, `infrastructure/research`, workflow
attempt isolation, GitHub optional composition, and workflow timeout handling were
not present in the tested tree.

## Delivery Verdict

| Check | Exact command | Result |
| --- | --- | --- |
| Mandatory smoke | `F:\github\NewsRoom\.venv\Scripts\python.exe -m scripts.dev smoke` | `1180 passed, 23 skipped`; source validation `0 errors, 0 warnings` |
| Focused Harness/Research | Command below | `379 passed` |
| Architecture | `F:\github\NewsRoom\.venv\Scripts\python.exe -m pytest tests/architecture -q` | `94 passed` |
| Change validation | `openspec validate harness-deterministic-gate-enforcement --strict` | valid |
| Repository OpenSpec validation | `openspec validate --all --strict` | `170 passed, 0 failed` |
| Compile | `F:\github\NewsRoom\.venv\Scripts\python.exe -m scripts.dev compile` | passed |
| Candidate whitespace | `git diff --check HEAD^ HEAD` | passed |
| Main index whitespace | `git diff --cached --check` | passed before candidate construction |

Focused command:

```powershell
F:\github\NewsRoom\.venv\Scripts\python.exe -m pytest `
  tests/framework/harness/control_plane `
  tests/framework/harness/runtime/test_replay.py `
  tests/framework/harness/test_serialization.py `
  tests/framework/harness/test_worker_result_contract.py `
  tests/framework/events/test_schema_catalog.py `
  tests/infrastructure/storage/events/test_harness_durable_event_integration.py `
  tests/business/research/workflows `
  tests/business/research/integration/test_paper_analysis_gate_enforcement.py `
  tests/business/research/integration/test_single_paper_loop_fake_runtime.py `
  tests/business/research/reader_repair/test_repair_service_side_effects.py -q
```

The only warnings were the pre-existing FastAPI `on_event` deprecation warnings.

## Requirements To Tests

| Requirement | Implementation evidence | Direct test evidence |
| --- | --- | --- |
| Versioned gate binding | `framework/harness/control_plane/gate_registry.py`; workflow preflight in `framework/harness/control_plane/harness.py` | `test_gate_registry.py`; `test_unknown_declared_gate_fails_before_any_event_or_worker_call`; `test_mandatory_gate_moving_version_alias_fails_before_run_creation` |
| Harness control-plane authority | Worker ingress reconstruction and forbidden fields in `framework/harness/workers/result.py` and `framework/harness/control_plane/harness.py` | `test_worker_result_contract.py`; `test_llm_cannot_route.py`; `test_worker_waiting_approval_status_cannot_create_approval_state` |
| Deterministic aggregation only | `framework/harness/quality/verdict.py`; verdict construction in `framework/harness/control_plane/harness.py` | `test_verdict_is_aggregated_from_gate_results_only`; `test_high_worker_quality_observation_cannot_override_failed_gate_or_route`; `test_on_verdict_route_uses_gate_verdict_instead_of_worker_observation` |
| Current-step gate selection | Mandatory and bound domain gates are separated in `HarnessControlPlane` | `test_each_verify_runs_mandatory_and_only_its_bound_gate_dependencies`; `test_declared_gate_cannot_be_shadowed_by_a_different_mandatory_implementation`; `test_same_bound_gate_instance_is_deduplicated_across_mandatory_and_declared_roles` |
| Fail-closed invalid gates | Stable invalid results and reason codes in `framework/harness/control_plane/harness.py` | `test_invalid_declared_gate_result_fails_closed`; `test_malformed_gate_details_become_a_stable_failed_result`; `test_on_verdict_route_without_declared_gate_fails_preflight` |
| Bounded deterministic outcomes | Existing scheduler and retry/replan budgets remain authoritative | `test_quality_gate_failed_routes_to_repair_step`; `test_max_replans_exhaustion_halts_run`; `test_max_turns_exhaustion_halts_run`; `test_missing_evidence_halts_after_replan_budget_is_exhausted` |
| Durable gate evidence and replay | Exact references, checksums, aggregate verdict, and decisions are committed through the existing event contract | `test_verify_transition_and_decision_history_bind_gate_evidence_and_verdict`; durable boundary recovery tests; SQLite integration tests; `tests/framework/harness/runtime/test_replay.py` |
| Research gate convergence | `paper_analysis_gates.py`, exact workflow declarations, and `ResearchSinglePaperRuntime.gate_registry` | `test_paper_analysis_registry_resolves_every_exact_reference`; `test_active_paper_gate_failure_records_exact_evidence_before_downstream_work`; `test_incomplete_research_registry_fails_before_source_or_artifact_calls`; workflow inventory tests |
| Side effects remain precondition-owned | Reader repair policy, namespace, lineage, and write-candidate checks run before writes | `tests/business/research/reader_repair/test_repair_service_side_effects.py` |

## Compatibility

- `HarnessStepSpec.quality_gate` remains a string and retains its serialized field
  shape. `test_versioned_gate_contracts_are_public_and_quality_gate_stays_a_string`
  locks this contract.
- The Harness event envelope remains `newsroom.harness-event/v1`. The safe
  `gate_evaluated` projection adds optional `reference`, `input_ref`, `result_ref`,
  `reason_code`, and `score` fields without changing the envelope or the existing
  required `gate`/`passed` fields.
- Public `ResearchAnalysisResult` response fields remain unchanged and are covered
  by `test_analyze_paper_use_case_runs_single_paper_loop_successfully` and smoke.
- Historical or malformed legacy gate projections remain readable but are marked
  unverified by `tests/framework/harness/runtime/test_replay.py`.

Intentional breaking changes are limited to the proposal:

1. Unversioned or moving gate references are rejected before run creation.
2. Worker `quality_score` and other control-shaped fields are rejected and cannot
   become Harness verdict or routing inputs.
3. The metadata-only `build_paper_rag_workflow_spec` and
   `build_reader_repair_workflow_spec` exports are removed.

## Replay And Recovery Matrix

| Boundary | Expected behavior | Test |
| --- | --- | --- |
| Incomplete VERIFY | Re-evaluate only the pinned deterministic gate; never rerun the worker | `test_verify_recovery_requires_and_reuses_exact_declared_gate_version` |
| Committed VERIFY | Reuse recorded evidence and verdict; do not rerun the gate or worker | `test_in_memory_recovery_reuses_committed_verify_evidence` |
| Missing committed gate event | Fail with `EventIncompleteHistoryError`; do not reconstruct or rerun | `test_recovery_rejects_committed_verify_with_missing_gate_evidence` |
| Pinned version unavailable | Fail with `unknown_gate_reference` | `test_verify_recovery_requires_and_reuses_exact_declared_gate_version` |
| Coordinated input checksum tamper | Fail with `EventStoreCorruptionError` | `test_recovery_rejects_coordinated_gate_input_reference_tampering` |
| Durable SQLite crash before/after VERIFY commit | Respect the commit boundary and recorded scheduler inputs | `test_sqlite_recovery_respects_verify_commit_boundary` |
| Offline replay | Expose recorded evidence without executing a gate, worker, or side effect | `test_replay_identifies_versioned_gate_evidence_without_reexecuting_it` |
| Legacy/malformed evidence | Keep readable and classify as unverified | `test_replay_marks_malformed_gate_evidence_unverified` |

## Workflow Retirement Audit

- Removed builders: `build_paper_rag_workflow_spec` and
  `build_reader_repair_workflow_spec`.
- Canonical production owners: `PaperRAGSession` and `ReaderRepairService`.
- Inventory: 19 retired declarations, classified as 10 `removed` and 9
  `precondition-owned`; `ArtifactPublicationGate` is explicitly `removed`.
- `test_retired_workflow_builder_has_no_production_reference` proves zero production
  references under repository runtime roots.
- `test_retired_workflows_have_no_dynamic_entry_or_persisted_replay_reference`
  proves zero dynamic entry or JSON/JSONL/YAML/TOML replay references.
- Independent candidate searches also returned `PRODUCTION_REFERENCES=0` and
  `PERSISTED_CONFIG_REFERENCES=0`.
- Project version is `0.1.0` and `git tag --list` returned zero tags. These facts
  reduce, but do not eliminate, the risk of an external private consumer.

## Migration

1. Custom workflow declarations must use exact `<gate-id>@<version>` references and
   register that version in an instance-scoped `DeterministicGateRegistry`.
2. Worker self-evaluation must use observational/domain-specific fields; it cannot
   use `quality_score`, verdict, route, approval, memory, or publication fields.
3. Callers of the removed paper-RAG builder migrate to `PaperRAGSession`; callers of
   the removed reader-repair builder migrate to `ReaderRepairService`.
4. Gate versions referenced by retained durable history must remain available for
   the retention/replay window. Existing history is never rewritten or backfilled.

## Rollback

- Roll back registry binding and Research composition together as one code release.
- Preserve the additive event reader/schema support and all already committed gate
  history; never rewrite events.
- Do not restore worker-provided verdicts, skip VERIFY, or restore metadata-only
  workflow builders as a second production path.
- If a gate implementation is faulty, register a corrected new version and retain
  the old version only for historical verification.

## Residual Risks

- Repository evidence cannot prove that an external private installation does not
  import either removed workflow builder. Release notes must call out the migration.
- No live credential, Postgres, Redis, Qdrant, or external source E2E was required or
  executed. In-memory and real SQLite durable contracts cover this change's storage
  boundary; backend-specific live validation remains an operational release check.
- Retaining pinned historical gate versions is an operational lifecycle obligation,
  not something a unit test can enforce after deployment.
- The shared main worktree contained parallel untracked `infrastructure/research`
  files with seven architecture-policy imports. They were absent from the staged
  candidate; the candidate architecture suite passed all 94 tests.

## Phase Status

This change is complete and ready to archive after its implementation commit. Phase
20 remains `IN_PROGRESS`; Research production composition, Tool approval/policy,
Source governance, Analysis quality, workflow graph convergence, and remaining
legacy cleanup require separate OpenSpec changes.
