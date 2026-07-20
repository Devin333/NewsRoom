# Harness side-effect authority closure evidence

## 1. Status and accountability

This file is the implementation evidence ledger for `harness-side-effect-authority-closure`. HAR-008 and HAR-009 remain open until accountable task `7.5` is complete. Supporting task checkboxes record implemented slices; they are not independent requirement owners.

- Parent specification commit: `14ce76bf`.
- Implementation baseline date: `2026-07-20` (`+08:00`).
- Initial OpenSpec ledger: `0/51`.
- Production cutover scope: Harness authority contracts plus Research artifact/terminal publication and run disposition.
- Explicitly excluded production claims: generic Tool, generic Harness Memory, AgentLoop, Workflow Tool runners, Reader Repair effects, and production skill release.

## 2. Pre-fix regression baseline

The exact focused baseline command was:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/framework/harness/test_contracts.py `
  tests/framework/harness/test_worker_result_contract.py `
  tests/framework/harness/control_plane/test_skill_evolution_budget.py `
  tests/framework/harness/skills/evolution `
  tests/business/research/workflows/test_workflow_gate_inventory.py `
  tests/infrastructure/research/test_filesystem_run_store.py `
  tests/interfaces/services/test_research_service.py `
  tests/business/research/integration/test_single_paper_loop_fake_runtime.py
```

Observed before implementation: `166 passed, 1 failed in 59.44s`. The failure was `tests/infrastructure/research/test_filesystem_run_store.py::test_concurrent_processes_serialize_latest_index_updates`; one spawned process exhausted the existing filesystem lock acquisition window and raised `ResearchRunStoreReason.LOCK_UNAVAILABLE`. This is retained as an exact red baseline and is rerun after the Research storage slice; it is not waived or rewritten as green.

Pre-fix behavioral oracles:

- `HarnessWorkerResult` accepted nested or alternate publication/promotion/authorization fields outside exact top-level `output` keys.
- Research `publish_artifacts` wrote canonical members sequentially during worker EXECUTE, so a later failure could leave visible earlier members.
- Research latest/list selected the newest committed record without an accepted disposition filter.
- `VersionedSkillReleaseRegistry.publish_release()` mutated releases, history, and active versions without resolving durable side-effect authority provenance.

## 3. File ownership matrix

| Surface | This change may modify | Excluded active owner / rule |
| --- | --- | --- |
| Harness authority | `framework/harness/side_effects`, worker result, Harness workflow declarations, control-plane safe projections/recovery | Do not change canonical event envelopes, event types, or `framework/events/schema/catalog.py` |
| Research runtime | `business/research`, `infrastructure/research`, Research composition/service and their focused tests | Do not modify legacy board/paper-radar modules or unrelated interface transports |
| Skill contract | `framework/harness/skills/evolution` and its contract tests | In-memory contract only; do not claim a production release store |
| Tool/Workflow runtime | Consume existing ports only | `framework/tool`, generic `framework/workflow`, Redis worker queue, shared MCP/interface, OpenAPI, and generated files are excluded |
| OpenSpec/docs | This change's `tasks.md`, `evidence.md`, and strict validation evidence | Do not rewrite unrelated active changes or generated indexes |

The starting worktree already contained unrelated Tool, Workflow, Event schema, Redis, MCP/interface, OpenAPI, script, and test changes. They remain unstaged and are not implementation evidence for this change.

## 4. Generic Harness Memory inventory

Static search and object-graph inspection found these relevant boundaries:

- `framework/harness/ports.py` and `framework/harness/memory/ports.py` declare `commit_write`; they do not compose a production writer.
- `interfaces/services/paper_rag_factory.py` may compose `ResearchRAGMemoryPort`, but `business/research/rag/adapters/memory_port.py` is recall-only and returns `REJECTED` from `commit_write`.
- `framework/harness/memory/fake.py` is the only committed `HarnessMemoryPort` writer found and is test-only.
- `PostgresReaderRepairMemoryPort` is a domain-specific production writer with `write_case`/`write_strategy`; it does not implement generic Harness `commit_write` and is not migrated by this Research-focused change.

Therefore no generic Harness Memory production writer is claimed here. Fake store/handler tests prove the authority contract only. A future production binding requires a named owning change and an explicit handler composition.

## 5. Implemented contract evidence

Initial typed-contract command:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/framework/harness/test_worker_result_contract.py `
  tests/framework/harness/test_serialization.py `
  tests/framework/harness/side_effects
```

Observed after the first contract slice: `77 passed`. It covers recursive direct/nested/channel rejection, explicit observations, strict candidate refs, immutable intent/decision/outcome JSON round trips, exact handler registry behavior, approval identity matching, scope isolation, idempotent outcome read-back, omission-compatible step/terminal policy serialization, and the Harness import boundary.

## 6. Control-plane authority and recovery evidence

### 6.1 Red baseline and bounded-ref repair

The initial control-plane command for tasks `1.2` and `3.1-3.9` was:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/framework/harness/control_plane/test_side_effect_authority.py `
  tests/framework/harness/control_plane/test_side_effect_durable_recovery.py
```

Observed before the final recovery repair: `7 passed, 11 failed`. Normal runs and
recovery both rejected successful step state because in-memory metadata and the
durable decision/outcome pair used different optional-field canonicalization.
The control plane now uses one bounded side-effect state-ref projection, records
the approval evidence ref on new step-success state, reconstructs omitted refs
from the durable store during recovery, and still rejects every conflicting ref.
It does not weaken authorization checksum comparison or replace the original
command ordinal, causation, effect id, scope, or idempotency identity.

The original 18-test baseline then passed, and the expanded matrix now reports:

```text
28 passed in 11.45s
```

### 6.2 Task coverage matrix

- `1.2`: gate failure, budget halt, approval wait/cancel, retry, and replan record
  candidate-worker calls independently from Tool, memory, published-artifact,
  release-history, and active-skill mutation probes. Rejected candidates leave
  all five commit counts at zero; retry/replan commit only attempt 2 once.
- `3.1`: unknown handlers, terminal kind conflicts, missing durable stores, and
  missing approval resolvers fail before `RUN_CREATED`, worker, or handler calls.
- `3.2`: worker authorization is bound to the recorded candidate result, exact
  run/step/attempt, handler/kind, passing VERIFY refs, aggregate verdict, budget,
  identity/subject scope, and resolved approval or pinned `not_required` ref.
  Gate, budget, approval, and scope mismatch tests retain zero effect writes.
- `3.3`: a worker-supplied `controller_terminal` intent is rejected; the actual
  controller-terminal intent is derived only after every step succeeds and is
  bound to policy, state checksum, completion input, gate history, scope, budget,
  approval evidence, handler, and persisted terminal attempt limit.
- `3.4`: completion decision/history projections expose bounded origin, scope,
  intent, handler, verdict, approval, decision, disposition, idempotency, attempt,
  and outcome refs without changing the decision-input top-level schema, event
  envelope, event type, or schema catalog.
- `3.5`: completion authorization is committed to deterministic history before
  the handler. The side-effect store durably records and scoped-reads the matching
  outcome before `STEP_SUCCESS` or `COMPLETE_RUN` can be committed.
- `3.6`: waiting approval never publishes, cancellation and stable non-success
  completion quarantine prepared outcomes, and retry/replan use new attempt and
  effect identities without copying an earlier approval.
- `3.7`: recovery handles zero or one dangling completion authorization, reuses
  its ordinal and causation, skips handlers for committed outcomes, reuses the
  original effect id after an external-effect crash, persists attempt exhaustion,
  and rejects multiple or mismatched dangling decisions.
- `3.8`: the pure offline decision kernel exposes authorization both with and
  without an outcome while calling no worker, handler, or mutation store.
- `3.9`: in-memory and reopened SQLite tests cover before-decision,
  decision-before-effect, external-effect-before-outcome,
  durable-outcome-before-transition, committed worker and terminal outcome
  recovery, one-intent validation, scope mismatch, and persisted worker/terminal
  retry exhaustion.

The complete focused contract command was:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/framework/harness/test_worker_result_contract.py `
  tests/framework/harness/side_effects `
  tests/framework/harness/control_plane/test_side_effect_authority.py `
  tests/framework/harness/control_plane/test_side_effect_durable_recovery.py `
  tests/framework/harness/control_plane/test_replay_history.py `
  tests/infrastructure/storage/harness
```

Observed result: `109 passed in 12.72s`.

### 6.3 Architecture, compile, and residual owners

The Harness-owned architecture subset passed:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/architecture/test_framework_harness_boundary.py `
  tests/architecture/test_harness_durable_event_boundary.py `
  tests/architecture/test_framework_workers_boundary.py `
  tests/architecture/test_skill_evolution_boundary.py
```

Observed result: `13 passed in 4.32s`.

Compileall over `framework/harness`, `infrastructure/storage/harness`, and their
focused tests passed. Full and change-scoped `git diff --check` passed; the full
command emitted only pre-existing CRLF normalization warnings in unrelated test
files. `openspec validate harness-side-effect-authority-closure --strict` passed.

The broader `tests/framework/harness` snapshot initially exposed two stale fake
callers in `tests/framework/harness/ports/test_mcp_policy.py`: `FakeMCPToolPort`
still emitted the intentionally forbidden executable `policy_decision` worker
field. The minimal caller migration renamed only that fake result field to the
non-executable `policy_observation`; it did not change MCP/Tool policy or any
production adapter. The complete Harness suite then passed `492 passed in
21.00s`. Adding the Research infrastructure boundary tests now produces `17
passed`; the earlier partial-pair import failures no longer reproduce.

### 6.4 Remaining evidence

Research terminal publication, broad cross-surface suites, mandatory smoke, and
deployment/rollback evidence are recorded in sections 8-13. Staged-only
verification remains open until task 7.7. Skill provenance evidence is recorded
in section 7.

## 7. Skill release authority evidence

### 7.1 Red baseline

Before the authority cutover, the focused adversarial command was:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/framework/harness/skills/evolution/test_release_and_rollback.py::test_unbound_release_cannot_mutate_registry_state `
  tests/framework/harness/skills/evolution/test_skill_evolution_port.py::test_caller_created_approved_decision_cannot_release
```

Observed result: `2 failed`. Both tests demonstrated that an approved-looking caller object reached `publish_release()`/`promote_candidate()` and mutated release state; this is the pre-fix oracle for tasks `1.5` and `6.2`.

### 7.2 Green contract evidence

The skill authority implementation and adversarial matrix pass with:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/framework/harness/skills/evolution `
  tests/framework/harness/control_plane/test_skill_evolution_budget.py `
  tests/framework/harness/runtime/test_skill_evolution_transcript.py `
  tests/architecture/test_skill_evolution_boundary.py
```

Observed result: `66 passed`.

The passing matrix verifies:

- immutable `SkillReleaseAuthorization` resolves candidate, held-out evaluation, promotion gate, approval evidence, package hash, exact release version, rollback plan, side-effect intent/decision and idempotency refs;
- registry publication and rollback resolve authority before the first release/history/active-version write, are idempotent, and reject tampered candidate/version/package/rollback/decision/approval/scope refs with write counts unchanged at zero;
- caller-created approved decisions, unregistered authority refs, and mutated canonical side-effect decisions fail closed;
- ordinary Harness worker observations never publish a skill without an explicit evolution handler;
- `FakeSkillEvolutionPort`, `VersionedSkillReleaseRegistry`, and their contract tests share the same resolver path, while both implementations expose `production_ready = False` and make no production-store claim;
- legacy unbound DTO serialization omits new authority fields, while bound releases/rollback plans serialize explicit authority and side-effect refs.

An earlier skill-slice snapshot reported `471 passed, 5 failed` in parallel
Event/MCP work. The current broader Harness result is `492 passed` as recorded in
section 6.3; neither snapshot is used as the focused skill-release authority
evidence.

## 8. Research run disposition and latest isolation evidence

### 8.1 Architecture red-to-green and focused matrix

Before the ownership correction, the focused Research command reported `72 passed, 2 failed`. Both failures came from `tests/architecture/test_infrastructure_boundary.py`: `infrastructure/research/filesystem_run_store.py` imported `business.research.application.run_disposition` directly.

The pure, I/O-free disposition policy now belongs to `business.research.domain.run_disposition`. The filesystem adapter depends only on the domain policy and the run-store port; application-only reconciliation remains in `business.research.application.run_disposition`. The current focused command is:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/business/research/application/test_run_disposition.py `
  tests/infrastructure/research/test_filesystem_run_store.py `
  tests/interfaces/services/test_research_service.py `
  tests/architecture/test_infrastructure_boundary.py
```

Observed result: `94 passed in 21.99s`.

The passing matrix proves:

- terminal status, deterministic quality evidence, identity/subject scope, artifact-ref evidence, and publication authority derive an explicit fail-closed accepted/quarantine disposition while retaining `save(record)`;
- in-memory and filesystem by-run reads retain terminal diagnostics while latest/list and normal analysis/reader/ask queries select accepted records only;
- accepted-then-halted, accepted-then-quality-failed, and failure-only behavior remains stable in process and after filesystem-backed service reconstruction;
- v1 root-scope binding accepts only an explicit immutable scope, absent/conflicting scope quarantines, and v1 bytes remain unchanged;
- v2 disposition metadata tampering is rejected even after an attacker recomputes the outer record checksum;
- mixed v1/v2 repair, concurrent accepted/quarantine writes, restart reads, and a newer quarantine record cannot replace accepted latest;
- scoped diagnostic reads expose legacy v1 failed-run refs as `legacy_quarantined` without making them visible through normal paper queries;
- bounded reconciliation rejects duplicate/malformed pending ids and paper/scope mismatches, preserves a stronger v2 quarantine decision in memory, and startup/lazy reads reuse an already reconciled record.

A broader Research/application/infrastructure/API/composition/architecture snapshot passed before the parallel artifact-publication files became partially paired:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/business/research/application `
  tests/infrastructure/research `
  tests/interfaces/services/test_research_service.py `
  tests/interfaces/api/test_research_api.py `
  tests/interfaces/api/test_research_contracts.py `
  tests/interfaces/composition/test_research_composition.py `
  tests/interfaces/composition/test_research_recorded_transport.py `
  tests/architecture
```

Observed result: `416 passed, 2 skipped in 280.93s`.

### 8.2 Completed Research recovery evidence

The paired Research composition files now provide a production v2 writer, strict dual
reader, startup/lazy reconciler, and scope-bound diagnostic artifact reader. The
current focused recovery command is:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/interfaces/composition/test_research_recovery_composition.py `
  tests/interfaces/composition/test_research_composition.py `
  tests/interfaces/composition/test_research_settings.py `
  tests/interfaces/services/test_research_service.py `
  tests/business/research/application/test_run_disposition.py `
  tests/infrastructure/research/test_filesystem_run_store.py
```

Observed as part of the focused Research matrix: `383 passed, 2 skipped` across
the full Research/application/infrastructure/composition selection. The targeted
recovery correction then passed `4 passed` for deferred terminal publication,
post-run `ValueError`, failed diagnostic persistence, and cleanup-error masking.

The evidence now covers:

- strict v1/v2 decoding, immutable v1 bytes, dual-reader/v2-writer settings, and
  rollback rejection when a target cannot read both versions;
- historical failed manifests classified as `legacy_quarantined`, with normal
  artifact reads denied and an explicit scope-bound diagnostic reader available;
- startup and lazy reconciliation from durable terminal publication, with zero
  worker/effect calls and idempotent accepted/quarantine projection;
- a finalized manifest without `COMPLETE_RUN` is deferred rather than written as
  immutable quarantine; a later success transition can reconcile the same run id
  to accepted without an identity conflict;
- post-run worker, preparation, terminal, and typed failure paths persist scoped
  v2 quarantine diagnostics while preserving accepted latest after restart;
- recovery persistence errors remain visible through exception cause/note and
  structured logging without changing the public Research error envelope;
- pre-run validation remains `invalid_request/400`, while a runtime `ValueError`
  after durable run creation is `research_run_failed/500`;
- candidate cleanup secondary failures never replace the primary worker/handler
  exception.

## 9. Research artifact publication and transport evidence

### 9.1 Focused authority/publication matrix

The exact focused commands and observed results were:

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/framework/harness/test_worker_result_contract.py `
  tests/framework/harness/side_effects `
  tests/framework/harness/control_plane/test_side_effect_authority.py `
  tests/framework/harness/control_plane/test_side_effect_durable_recovery.py `
  tests/framework/harness/control_plane/test_replay_history.py `
  tests/framework/harness/control_plane/test_skill_evolution_budget.py `
  tests/infrastructure/storage/harness `
  tests/framework/harness/skills/evolution `
  tests/framework/harness/runtime/test_skill_evolution_transcript.py
```

Observed: `173 passed in 13.42s`.

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/business/research/application/test_run_disposition.py `
  tests/business/research/workflows `
  tests/business/research/integration/test_research_artifact_publication.py `
  tests/business/research/integration/test_paper_analysis_gate_enforcement.py `
  tests/business/research/integration/test_single_paper_loop_fake_runtime.py `
  tests/infrastructure/research `
  tests/interfaces/services/test_research_service.py `
  tests/interfaces/composition/test_research_composition.py `
  tests/interfaces/composition/test_research_settings.py `
  tests/interfaces/composition/test_research_recovery_composition.py
```

Observed: `383 passed, 2 skipped in 140.61s`. The two skips are Windows
symlink-privilege skips in `tests/infrastructure/research/test_artifact_port.py`
(WinError 1314); junction/path validation remains covered by the green cases.

The artifact-specific behavior includes VERIFY rejection with zero handler calls,
hidden prepared candidates, Nth-member failure with zero canonical visibility,
effect-id idempotency, terminal history cutoff, durable outcome read-back, and
worker object-graph isolation. The production composition test confirms the v2
run store and reconciler are wired, while generic Tool/Memory/skill production
stores remain explicitly outside this change.

### 9.2 HTTP/MCP/SDK and recorded transport

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/interfaces/api/test_research_api.py `
  tests/interfaces/api/test_research_contracts.py `
  tests/interfaces/services/test_mcp_application_service.py `
  tests/interfaces/composition/test_research_entrypoint_defaults.py `
  tests/interfaces/composition/test_research_errors.py `
  tests/interfaces/composition/test_research_rag_composition.py
```

Observed: `51 passed in 4.96s` (36 expected FastAPI deprecation warnings).

```powershell
.\.venv\Scripts\python.exe -m pytest -q `
  tests/interfaces/composition/test_research_recorded_transport.py
```

Observed: `2 passed, 4 warnings in 207.49s`. The recorded transport proves the
same error/trace shapes and accepted artifact references through local MCP,
server adapter, and restart reconstruction; no live credentials were used.

## 10. Broad compatibility and remaining delivery evidence

The task 7.2 broad commands produced:

- `tests/framework/harness`: the first run reported `490 passed, 2 failed in
  22.42s` from the stale fake `policy_decision` field. After the minimal
  observation-field caller migration, the full suite passed `492 passed in
  21.00s` without changing MCP/Tool policy semantics.
- `tests/business/research`: `792 passed, 23 deselected in 363.70s`. The
  deselections are the repository-wide `not live_research_e2e` marker; live
  arXiv/Qdrant/Postgres/LLM credentials were not provided.
- `tests/infrastructure/research`: `200 passed, 2 skipped in 27.83s`. Both skips
  are Windows symlink-creation privilege failures (WinError 1314) in artifact
  path-hardening tests.
- `tests/interfaces`: `957 passed, 2 skipped, 1 deselected in 354.97s`. The
  deselection is `live_research_e2e`; the skips are the two interface storage
  symlink tests when Windows cannot create a link. The 524 warnings are existing
  FastAPI startup-event deprecations plus two Qdrant version-probe warnings.

Tasks `7.5` and `7.7` remain open until evidence accountability and staged-only
commit are completed.

## 11. Baseline archive, deployment, and rollback order

`research-runtime-production-composition` was validated strictly with all
`46/46` tasks complete, then archived before this change's persistence delta:

```powershell
openspec validate research-runtime-production-composition --strict
openspec archive research-runtime-production-composition -y
```

The archive command synchronized seven `research-production-composition`
requirements, four `research-run-persistence` requirements, and one modified
`research-runtime` requirement into the main specs, then moved the baseline to
`openspec/changes/archive/2026-07-19-research-runtime-production-composition/`.
The UTC archive date differs from the local `2026-07-20` work date; the actual
CLI path is authoritative. The current change then passed strict validation on
top of those synchronized main specs.

Deployment remains expand-then-write: deploy a build whose configured reader
supports v1 and v2, verify mixed-version repair and scoped quarantine reads,
then enable the v2 writer. `ResearchRunStoreSettings` rejects a v2 writer unless
both the active reader and rollback target retain `("v1", "v2")`; v1 bytes are
never rewritten. Rollback may disable new v2 writes and return to a qualified
dual-reader build, but may not restore pre-VERIFY publication, remove v2 records,
or expose quarantine through accepted/latest readers.

## 12. Strict specification and diff validation

After the baseline archive and the synchronized-spec EOF repair, the final
working-tree validation commands produced:

```text
openspec validate harness-side-effect-authority-closure --strict -> valid
openspec validate --all --strict -> 510 passed, 0 failed
git diff --check -> passed
```

`git diff --check` emitted only existing CRLF normalization warnings for
`tests/architecture/test_infrastructure_boundary.py` and
`tests/business/layers/analysis/quality/test_citation_editor.py`; neither file is
owned or staged by this change.

## 13. Compile and mandatory smoke

```powershell
.\.venv\Scripts\python.exe -m scripts.dev compile
.\.venv\Scripts\python.exe -m scripts.dev smoke
```

Compile completed successfully. The first smoke run identified only the stale
`FakeMCPToolPort.policy_decision` caller (`1425 passed, 2 failed, 23 deselected`),
which was migrated to an explicit non-executable observation. The mandatory
rerun then passed:

```text
1427 passed, 23 deselected, 22 warnings in 636.79s
sources validate: is_valid=true, error_count=0, warning_count=0
```

The 23 deselections are the configured `live_research_e2e` marker. The warnings
are existing FastAPI startup-event deprecations. No test was skipped, deselected,
or weakened to repair the MCP caller regression.

## 14. HAR accountability and residual limits

The single accountable completion task now has an explicit evidence map:

| Requirement group | Supporting tasks | Evidence sections | Status |
| --- | --- | --- | --- |
| HAR-008 Harness authority/replay | `1.1`, `2.1-2.8`, `3.1-3.8`, `6.4` | 5, 6, 7, 9, 12, 13 | Complete in this change |
| HAR-009 Research/skill side-effect closure | `1.2-1.5`, `1.7`, `2.5-2.8`, `3.2-3.9`, `4.1-5.7`, `6.1-6.3` | 6-9, 11-13 | Complete in this change |

Representative exact nodes anchoring those suite-level commands are:

- `tests/framework/harness/test_worker_result_contract.py::test_worker_result_rejects_nested_decision_aliases_in_all_untyped_channels`;
- `tests/framework/harness/control_plane/test_side_effect_authority.py::test_gate_failure_never_calls_side_effect_handler`;
- `tests/framework/harness/control_plane/test_side_effect_durable_recovery.py::test_sqlite_terminal_recovery_reuses_publication_outcome_before_run_success`;
- `tests/business/research/integration/test_research_artifact_publication.py::test_publish_output_schema_failure_calls_no_handler_and_has_zero_visibility`;
- `tests/interfaces/composition/test_research_settings.py::test_v2_writer_rejects_non_dual_reader_or_rollback_target`;
- `tests/infrastructure/research/test_filesystem_run_store.py::test_mixed_v1_quarantine_and_v2_accepted_repairs_latest_without_v1_rewrite`;
- `tests/framework/harness/skills/evolution/test_release_authority.py::test_ordinary_harness_run_observations_cannot_publish_skill`.

The pre-fix oracles are intentionally mixed evidence: section 2 records the
worker-ingress/Research-latest/partial-publication construction probes, section
6.1 records the control-plane red run (`7 passed, 11 failed`), section 7.1
records the two failing unbound skill-release nodes, and section 8.1 records the
architecture red run (`72 passed, 2 failed`). Each is replaced by a green
regression in the staged candidate rather than retained as an expected-failure
test.

Compatibility evidence covers unchanged HTTP/MCP/SDK response envelopes, stable
artifact URI/payload/checksum contracts, v1 byte-stable dual reads, additive
history projections, offline replay with zero live calls, and the explicit
`policy_observation` migration for the internal MCP fake. Migration and rollback
order are in section 11; strict validation and smoke are in sections 12-13.

Residual limits are explicit: live arXiv/LLM/Qdrant/Postgres credentials were not
used; 23 live tests remain deselected by the repository default; Windows symlink
privilege caused four non-security-path skips across broad suites; and this
change does not claim generic Tool, generic Harness Memory, production skill
release storage, distributed exactly-once transactions, or multi-host recovery.
Those surfaces retain their named OpenSpec owners and require separate live
deployment evidence.

## 15. Isolated staged-only candidate

The index was rebuilt from the audited ownership lists and contained 85 paths.
An excluded-owner pattern scan returned no Event catalog, generic Tool/Workflow,
Redis worker, OpenAPI, shared MCP/interface, `scripts/dev.py`, or generated path.
`git write-tree` produced the pre-evidence code candidate tree
`6929cf4ac49c57abd97f84098cf2d8705d6b0594`; a temporary detached worktree from
that tree, independent of all unstaged active-change files, produced:

```text
openspec validate harness-side-effect-authority-closure --strict -> valid
openspec validate --all --strict -> 183 passed, 0 failed
scripts.dev compile -> passed
focused staged selection -> 122 passed
git diff-tree --check HEAD^ HEAD -> passed
scripts.dev smoke -> 1427 passed, 23 deselected, 22 warnings
sources validate -> is_valid=true, error_count=0, warning_count=0
```

The 23 deselections and 22 warnings have the same configured live-E2E and
FastAPI-deprecation causes recorded in section 13. The temporary verification
commit/worktree is not a release commit and is removed after evidence capture.
The only subsequent candidate change is this evidence record itself.
