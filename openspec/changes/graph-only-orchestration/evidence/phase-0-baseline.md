# Graph-only Phase 0 baseline

Captured on 2026-08-13 from repository tree
`419a3d579f7c9066443e38af158a721a9f6f101e` at commit
`8511962f2c7406b467d23bde122a08818c760743`.

## Scope

This evidence is planning-only. `harness-workflow-graph-runtime` is still the
hard prerequisite for code apply. Its remaining release task depends on the
external durable-event qualification chain, so this baseline does not modify
runtime source or claim production cutover readiness.

The machine-readable authorities are:

- `production-dependency-inventory.json` for all 92 tracked
  `framework/workflow` files, external production imports, root exports,
  registries, reflection strings, and CLI/API/MCP/SDK entrypoints.
- `persistence-environment-inventory.json` for run manifests, events,
  checkpoints, replay records, indexes, Research run records, conversation
  cursors, and AgentLoop iteration checkpoints.
- `research-graph-golden-baseline.json` for the current static and opt-in
  dynamic Research Graph definitions, normalized checksums, deterministic gate
  evidence, terminal publication evidence, and recorded-only replay evidence.
- `active-workflow-change-audit.json` for every active change whose directory
  name contains `workflow`, plus `business-board-workflow-hardening` because it
  expresses a business workflow without owning orchestration authority.

## Verified facts

- `framework/workflow` contains 92 tracked files.
- `framework/harness/workflow` contains 20 tracked files.
- Static AST scanning finds 9 production callers outside
  `framework/workflow` and 29 production callers outside
  `framework/harness/workflow`.
- `framework.workflow.__all__` currently exposes 302 names, including
  `WorkflowRunner`, `WorkflowExecutor`, and `AgentLoopStepRunner`.
- The default step-runner registry constructs `AgentLoopStepRunner`,
  `SubworkflowStepRunner`, routing, join, and parallel runners.
- The current static Research Graph checksum is
  `sha256:3dbf9103e3a2360629c84eecd06bd250e15f03cf89c216fa815faeb686821d67`.
- The current opt-in dynamic Research Graph checksum is
  `sha256:127748300a04d38f46ef0dc85e34a01621298d889683fea033ace56ec2661bfa`.
- The existing Graph migration golden reports a successful Research result,
  11 Graph-native decisions, unique decision checksums, zero legacy transition
  events, and one committed publication effect.
- The current Graph checkpoint protocol has only an in-memory repository
  implementation; a production durable `HarnessGraphCheckpointStore` binding is
  therefore an explicit cutover prerequisite, not an assumed deployed store.

## Pending confirmations

Repository defaults are inventory evidence, not proof of deployed topology.
Managed environment identities, actual resolved roots/DSNs, record counts,
maintenance-window owner, rollback approver, deletion commits, and archive
commits remain `pending_external_confirmation` or `null` in the JSON files.
Those fields must be resolved before Phase 0 exit and before any offline data
migration or destructive deletion.

## Reproduction

```powershell
git rev-parse HEAD
git rev-parse 'HEAD^{tree}'
git ls-files framework/workflow | Measure-Object
rg -l "framework\.workflow" framework business interfaces infrastructure scripts --glob '*.py' --glob '!framework/workflow/**'
rg -l "framework\.harness\.workflow" framework business interfaces infrastructure scripts --glob '*.py' --glob '!framework/harness/workflow/**'
.\.venv\Scripts\python.exe -m pytest tests/framework/harness/workflow/test_graph_migration_goldens.py
openspec validate graph-only-orchestration --strict
```
