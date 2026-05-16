# Workflow Runtime Contract Tests

This directory owns the production contract suite for the workflow runtime. The
tests are grouped by stable runtime contracts so feature tests can grow without
making CI discovery ambiguous.

## Contract Groups

| Contract | Scope | Primary Test Files |
| --- | --- | --- |
| C01 | Spec compiler graph and dataflow contracts | `test_workflow_compiler_*.py`, `test_compiler_*_contract.py` |
| C02 | Data buffer permission, diff, lineage, redaction | `test_data_buffer_*.py`, `test_buffer.py` |
| C03 | Routing conditions and routing evaluations | `test_routing.py`, `test_routing_contract.py` |
| C04 | Scheduler linear, fan-out, join, resume behavior | `test_scheduler_*.py` |
| C05 | Retry, timeout, fallback, blocked failure behavior | `test_retry_timeout_failure.py`, `test_executor.py` |
| C06 | Checkpoint envelope, corruption, migration, resume | `test_checkpoint_*.py` |
| C07 | Artifact publishers and manifest governance | `test_artifact_publishers.py`, `test_manifest_contract.py` |
| C08 | Event ordering and post-run operation events | `test_event_ordering_contract.py` |
| C09 | Step runner behavior, registry, capabilities | `test_step_runner*.py`, `test_target_step_runners.py` |
| C10 | Human review pause, resume, route, permission | `test_human_review_*.py` |
| C11 | Parallel, join, subworkflow contracts | `test_parallel_*.py`, `test_join_contract.py`, `test_subworkflow_*.py` |
| C12 | Run operation cancel, resume, rerun, skip, blocked | `test_run_operations_*.py` |
| C13 | Diagnostics, replay, compare, health report | `test_run_diagnostics.py`, `test_run_replay_bundle.py`, `test_run_compare.py`, `test_run_health_report.py` |
| C14 | Budget and resource governance | `test_resource_policy.py`, `test_global_budget_policy.py`, `test_budget_*.py`, `test_runtime_safety_policy.py` |

## Naming Rules

- New workflow runtime contract tests live in this directory.
- Prefer `test_<contract_area>_contract.py` for cross-cutting contracts.
- Keep domain workflow tests under `tests/workflows`.
- Use `helpers.py` for small workflow builders and artifact readers instead of
  copying setup code across tests.
