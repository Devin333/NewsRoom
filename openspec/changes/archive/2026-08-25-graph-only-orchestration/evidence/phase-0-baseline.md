# Graph-only Phase 0 baseline

Captured on 2026-08-13 from repository tree
`419a3d579f7c9066443e38af158a721a9f6f101e` at commit
`8511962f2c7406b467d23bde122a08818c760743`.

The persistence inventory was corrected and reverified on 2026-08-14 against
tree `0bdec216e80fd0528befe20fbfd9ac22e2c6f342` at commit
`c4b4bd7cb196fdd407a9f5e095302e18cd4fa05f`.

The immutable architecture-freeze planning baseline remains anchored at tree
`1a94ff8e10886f317ed26727ef21392f88c8d44f` at commit
`0ea3223ee073dece45b232ca9cd94184f5e128b6`. The live dependency and
persistence overlays were refreshed on 2026-08-14 against tree
`ed9cf6ad4050e4729600d236621bd0878972aa67` at commit
`30178e151837d39db765bc1a8e605bc23d1ae3b2`, after Graph artifact governance
was implemented and archived.

## Scope

This evidence is planning-only. `harness-workflow-graph-runtime` is still the
hard prerequisite for code apply and remains `99/100`. Its Runtime Safety and
Side-effect Authority dependencies now satisfy their exact current repository
contracts. The only upstream release blocker is Durable Event task `9.5`,
followed by its final status task `10.5`: the external trust activation,
ordered D -> A -> B -> deploy -> C compatibility chain, and independent
rollback qualification do not exist. Therefore this baseline does not modify
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
- `architecture-freeze-gate-contract.json` for the future AST gate's immutable
  snapshot, monotonic debt rule, legacy schema writer classification,
  migration-reader exception policy, diagnostics, and installation tests.

## Verified facts

- `framework/workflow` contains 92 tracked files.
- `framework/harness/workflow` contains 20 tracked files.
- Static import scanning finds 10 production callers outside
  `framework/workflow` and 38 production callers outside
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
- The persistence inventory now records 23 distinct store/record classes. The
  2026-08-14 correction adds Harness side-effect authority, dynamic TaskPlan
  state, subagent attempt bundles, Graph result payloads, materialization
  attempts, cache entries, quota reservations, durable Graph result lineage,
  the Graph artifact governance ledger, and physical lifecycle state; these
  contracts cannot be inferred from the generic artifact-index row.
- Production Research composition binds `SQLiteHarnessSideEffectStore` below
  `research_root`, stores TaskPlan documents and subagent bundles below the
  artifact root, and sends TaskPlan events through the configured durable event
  runtime.
- Commit `3235b126` adds `LocalJsonArtifactCatalog`, and commits `a54f5e4e` and
  `ea8e6e82` add `SQLiteGraphResultStore` plus explicit Research production
  composition for the catalog, quota, cache, attempt ledger,
  `ResultMaterializer`, Graph result committer, Tool/SubAgent materialization,
  and durable result lineage. The bindings are activated only in `enforce` or
  `read_only`; the repository default remains `shadow`.
- Commit `167caff5` adds catalog/lineage-backed approved artifact context
  loading, while `b4c3f077` and `a6037ec6` prove accepted/gate-failed Research
  cutover, offline LLM/source/Tool/MCP/SubAgent recovery, and bounded GraphState
  projections. Internal graph-result artifacts remain ref-only and cannot
  acquire publication authority.
- `research-graph-artifact-cutover` is archived locally at
  `openspec/changes/archive/2026-08-14-research-graph-artifact-cutover` with all
  tasks complete. Repository composition and tests establish implementation
  readiness, not deployed store locations, counts, owners, backups,
  maintenance windows, or rollback authority; master task `1.8` remains open.
- `graph-artifact-cost-retention` is archived locally at
  `openspec/changes/archive/2026-08-14-graph-artifact-cost-retention`. It adds
  `framework/harness/artifacts/{catalog,governance,reporting,runtime}`,
  `SQLiteGraphResultStore` schema 2 governance tables,
  `FilesystemGraphArtifactLifecycle`, production composition, and the
  `news storage graph-artifacts` operator surface. Its proposal, design, and
  completion evidence explicitly do not remove the legacy Workflow artifact
  writer or claim that a production retention window elapsed.
- The retained Graph-native Artifact owner is therefore not a deletion target.
  The remaining migration surface is the legacy manager, Research publisher,
  inspection caller, and manifest/hash bridge. In particular,
  `infrastructure/research/graph_artifact_lifecycle.py` imports
  `framework.workflow.runtime.manifest.manifest_hash` and must migrate to an
  artifact-owned Graph terminal-manifest contract without losing GC,
  accounting, reporting, or alert behavior.
- The local unmanaged workspace has no configured storage environment
  overrides. Its side-effect database is store schema 2 with zero decisions,
  attempt records, attempt leases, and outcomes; there are also zero local
  TaskPlan documents and subagent bundles. These are local observations only,
  not managed-environment inventory or deletion authority.
- The current prerequisite refresh verifies `framework-runtime-safety-hardening`
  at `38/38`, `harness-side-effect-authority-closure` at `51/51`, and
  `durable-event-runtime` at `53/55`. Nineteen source SHA-256 fingerprints and
  seven release commits were checked against the current tree and HEAD.
- The Phase 4/5 Graph artifact and replay selection passes with `153 passed`,
  `3 skipped`. The archived governance change records `219 passed, 2 skipped`
  for framework/infrastructure governance, `110 passed` for Research/CLI,
  `134 passed` for architecture, and mandatory smoke with `2309 passed`,
  `23 deselected`, zero source-validation errors, and zero warnings.
- A `2026-08-14` live refresh records ten pre-freeze dependency-drift rows.
  The original row is `framework/harness/runtime/result_canonical.py`, added by
  `graph-artifact-result-contract`. The four subsequent Graph result commits
  add six exact `framework.harness.workflow` import rows in
  `graph_result_lineage.py`, `graph_result_projection.py`,
  `graph_result_runtime.py`, `materializer.py`, and
  `tool_result_adapter.py` and `subagent_result_adapter.py`. The Research
  cutover adds `graph_result_committer.py` and `artifact_context.py`. Artifact
  governance then adds `graph_artifact_lifecycle.py` as the tenth row. All ten
  rows have
  exact path, line, symbol, content
  fingerprint, owner change, owner commit, current callers, and disposition in
  `production-dependency-inventory.json`.
- The Graph result and Research cutover commits add no `framework.workflow`,
  `WorkflowRunner`, or `WorkflowExecutor` reference. Artifact governance adds
  one `framework.workflow.runtime.manifest` import for physical lifecycle
  manifest updates, while adding no runner/executor authority. All ten rows
  remain pre-install migration debt even where their owner change is archived;
  they do not authorize further legacy imports.
- Task `1.6` must reject equivalent new imports after the prerequisite is
  archived and the freeze gate is installed. Until then, inventory rows are
  migration inputs and must not be treated as an allowlist for further drift.
- The planned gate baseline contains 92 `framework.workflow` files, 20
  `framework.harness.workflow` files, 466 exact AST import-edge rows (468
  occurrences: 87 external and 381 internal), and 22 structured
  `WorkflowRunner`/`WorkflowExecutor` occurrences. Baseline updates are
  subtract-only; count-only and path-only allowlists are forbidden.
- The gate treats legacy schema reads/upcasts separately from writes. New data
  flow from a legacy schema id into manifest, event, projection, checkpoint, or
  store/publish sinks fails closed; a future migration-only reader requires an
  exact expiring exception under task `8.1` and cannot be imported by Graph
  runtime.
- A live GitHub recheck on 2026-08-14 found zero rulesets, releases, tags,
  deployments, webhooks, environments, Actions secrets, and Actions variables;
  `main` remains unprotected and `Devin333` remains the only collaborator with
  admin permission. These facts cannot satisfy independent governance,
  deployment observation, consumer-owner approval, or managed-environment
  ownership.
- The same refresh found remote CI run `31794484784` failed because two
  committed Harness tests read the ignored active-change file
  `openspec/changes/harness-workflow-graph-runtime/evidence/schema-version-registry.json`.
  Commit `8f1e4c83900ca151352d932312bbbdb3b9e04814` moves the exact tested registry
  sections into tracked fixture
  `tests/fixtures/harness/schema_version_registry_v2.json` and resolves the
  path from `__file__`, so a clean checkout and a later OpenSpec archive do not
  remove the contract lock. Verification passed with `2 passed` targeted,
  `2134 passed, 23 deselected` for `test-workflow-domain`, mandatory smoke at
  `2309 passed, 23 deselected`, clean source validation, and OpenSpec strict
  validation at `533 passed, 0 failed`. This repository delivery repair does
  not satisfy or weaken the external D/A/B/C and rollback qualification gates.

## Pending confirmations

Repository defaults are inventory evidence, not proof of deployed topology.
Managed environment identities, actual resolved roots/DSNs, record counts,
maintenance-window owner, rollback approver, deletion commits, and archive
commits remain `pending_external_confirmation` or `null` in the JSON files.
Those fields must be resolved before Phase 0 exit and before any offline data
migration or destructive deletion. The Durable Event external authority chain
is independently required before the prerequisite can be completed and
archived. Repository tests cannot manufacture any of these external facts.

## Reproduction

```powershell
git rev-parse HEAD
git rev-parse 'HEAD^{tree}'
git ls-files framework/workflow | Measure-Object
rg -l "framework\.workflow" framework business interfaces infrastructure scripts --glob '*.py' --glob '!framework/workflow/**'
rg -l "framework\.harness\.workflow" framework business interfaces infrastructure scripts --glob '*.py' --glob '!framework/harness/workflow/**'
rg -n "framework\.workflow|manifest_hash|FilesystemGraphArtifactLifecycle" infrastructure/research/graph_artifact_lifecycle.py framework/harness/artifacts interfaces/composition/research_graph_artifacts.py
rg -n "framework\.harness\.workflow|freeze_json|thaw_json" framework/harness/runtime/result_canonical.py framework/harness/runtime/result_models.py framework/harness/runtime/result_policy.py framework/harness/runtime/__init__.py interfaces/composition/research_settings.py
Get-FileHash -Algorithm SHA256 openspec/changes/graph-only-orchestration/evidence/architecture-freeze-gate-contract.json
.\.venv\Scripts\python.exe -m pytest tests/framework/harness/workflow/test_graph_migration_goldens.py
.\.venv\Scripts\python.exe -m pytest tests/framework/harness/workflow/test_graph_preflight.py tests/framework/harness/control_plane/test_parallel_graph_control_plane.py tests/framework/shared/test_attempt_execution_integrity.py tests/framework/tool/runtime/test_tool_attempt_safety.py tests/infrastructure/storage/harness/test_sqlite_side_effect_store.py tests/infrastructure/storage/events/test_harness_durable_event_integration.py
.\.venv\Scripts\python.exe -m pytest tests/framework/harness/runtime/test_materializer.py tests/framework/harness/runtime/test_graph_result_runtime.py tests/framework/harness/runtime/test_tool_result_adapter.py tests/framework/harness/runtime/test_subagent_result_adapter.py tests/framework/harness/runtime/test_result_policy.py tests/framework/harness/subagents/test_handoff_schema_gate.py tests/framework/tool/runtime/test_tool_result_envelope.py tests/framework/tool/runtime/test_tool_result_standardization.py tests/framework/tool/runtime/test_mcp_result_persistence.py tests/infrastructure/research/test_artifact_port.py tests/architecture/test_harness_graph_result_boundary.py tests/architecture/test_harness_tool_result_boundary.py tests/architecture/test_harness_subagent_result_boundary.py -q
.\.venv\Scripts\python.exe -m pytest tests/framework/harness/artifacts/test_governance_contracts.py tests/framework/harness/artifacts/test_governance_runtime.py tests/framework/harness/artifacts/test_governance_reporting.py tests/infrastructure/storage/test_graph_artifact_governance_store.py tests/infrastructure/storage/test_graph_artifact_gc_ledger.py tests/infrastructure/research/test_graph_artifact_lifecycle.py tests/infrastructure/research/test_graph_artifact_governance_integration.py tests/interfaces/composition/test_research_graph_artifacts.py
.\.venv\Scripts\python.exe -m scripts.dev smoke
openspec instructions apply --change graph-only-orchestration --json
openspec validate graph-only-orchestration --strict
openspec validate --all --strict
```
