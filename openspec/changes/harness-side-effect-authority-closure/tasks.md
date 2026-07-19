## 1. Regression Baseline And Ownership

- [ ] 1.1 Add a worker-result adversarial matrix covering direct, nested, alternate, diagnostics, and metrics authorization/memory/publication/promotion fields while preserving explicit observations and typed candidate payloads; separately assert strict candidate-artifact ref typing without claiming that ref strings are executable decision payloads.
- [ ] 1.2 Add pre-fix control-plane probes for gate failure, budget halt, approval pending/cancel, retry, and replan that assert candidate-worker calls separately from Tool, memory, published artifact, release, and active-skill commit counts.
- [ ] 1.3 Add Research accepted-then-halted, accepted-then-quality-failed, failure-only, and historical-record regressions proving failed diagnostics remain queryable without replacing accepted latest; cover both `get_latest_by_paper_id()` and the `ResearchApplicationService._record_for_paper() -> list_by_paper_id()` path through `get_analysis`, `get_reader`, and `ask_paper` in-process and after filesystem-backed service reconstruction.
- [ ] 1.4 Add Research artifact publication regressions for VERIFY failure and injected Nth-member failure, asserting zero canonical manifest/index visibility and isolated candidate cleanup.
- [ ] 1.5 Add skill-release regressions proving forged or unbound promotion objects and ordinary Harness runs cannot mutate release history or active versions.
- [ ] 1.6 Record exact red commands/oracles and a file-ownership matrix in `evidence.md`; exclude active Tool, Workflow, Event schema, Redis, generic MCP/interface, OpenAPI, and generated-file owners.
- [ ] 1.7 Inventory every production `HarnessMemoryPort.commit_write` composition and call path; record AST/object-graph evidence when no production writer exists, or route any real writer to a named owning change and block generic Memory production-complete claims here without expanding this Research-focused cutover or treating fake-only coverage as production integration.

## 2. Typed Side-Effect Contracts

- [ ] 2.1 Implement immutable singular `HarnessSideEffectIntent`, origin, kind, canonical candidate/prepared/quarantine/accepted disposition, authorization decision, and outcome models with stable checksums, worker-versus-controller-terminal identity rules, exact run/step-or-terminal/attempt identity, identity/subject scope refs, atomic groups, retention metadata, and JSON round trips.
- [ ] 2.2 Implement exact versioned handler references, immutable bindings, and an instance-scoped `HarnessSideEffectRegistry` with duplicate, unknown, kind-mismatch, and version validation.
- [ ] 2.3 Extend `HarnessStepSpec` with an optional exact side-effect reference that is omitted when absent, preserving historical workflow serialization and checksums.
- [ ] 2.4 Extend `HarnessWorkerResult` with zero-or-one typed `effect_intent`, reject multiple handlers/kinds per step, and add recursive reserved-path validation across supported untyped worker mappings with stable codes and sorted paths.
- [ ] 2.5 Add side-effect handler/store protocols plus counting in-memory contract implementations for durable outcome read-back, commit, quarantine, lookup, idempotency, identity/subject scope isolation, and namespace isolation.
- [ ] 2.6 Add an injected read-only approval-evidence resolver that validates one durable approval against run, step, attempt, effect id, candidate checksum, identity scope, subject scope, and decision version without importing Tool store implementations.
- [ ] 2.7 Export the new contracts through the approved `framework.harness` surfaces and add serialization, immutability, origin/scope, and import-boundary tests.
- [ ] 2.8 Add optional versioned `HarnessTerminalSideEffectPolicy` serialization under the run/workflow terminal-policy projection, with exact handler/kind, approval requirement or pinned `not_required` evidence, inherited gate/budget rules, retry limit, omission-compatible historical checksums, and strict legacy parsing.

## 3. Control-Plane Authority And Replay

- [ ] 3.1 Bind every declared step and terminal side-effect reference during Harness preflight and reject missing/conflicting/unknown-version handler or policy bindings before `RUN_CREATED` or any worker call.
- [ ] 3.2 Build worker-originated authorization only from the recorded intent, exact VERIFY/gate evidence, current budget, workflow declaration, matching identity/subject scope, and approval resolved by task 2.6; worker observations must remain excluded.
- [ ] 3.3 Add a distinct controller-terminal intent path bound to the versioned policy, current state checksum, completion input, scope refs, inherited aggregate gate/budget evidence, approval or pinned `not_required` evidence, persisted terminal attempt counter, and exact handler after all step outcomes are durable; reject worker-created terminal intents.
- [ ] 3.4 Persist bounded origin, scope, intent, handler, gate, approval, budget, decision, disposition, and outcome refs through existing decision/history safe projections without changing `HARNESS_DECISION_INPUT_SCHEMA` top-level fields, event envelopes, event types, or schema catalog; coordinate the projection with the durable-event owner.
- [ ] 3.5 Persist canonical authorization in the existing `COMPLETE_STEP` or terminal decision history before invoking the handler, then require a durably stored and scoped-read-back-verified outcome before `STEP_SUCCESS`, downstream routing, or `COMPLETE_RUN` references it.
- [ ] 3.6 Quarantine eligible candidates after recorded terminal/cancel decisions while keeping waiting-approval candidates non-published; bind retry/replan candidates, scopes, approvals, and effect ids to new attempt identities.
- [ ] 3.7 Reconcile exactly one dangling `COMPLETE_STEP` or controller-terminal authorization by reusing its ordinal and causation; resolve a stored outcome first, otherwise invoke the idempotent handler with the original effect id only while the persisted effect-attempt budget remains, and fail closed on multiple/conflicting matches or `effect_retry_exhausted`.
- [ ] 3.8 Extend legacy-history dual-read and offline transcript/replay projections for origin, scope, intent, authorization, disposition, idempotency, and outcome refs, proving offline replay calls no worker or effect port even when an outcome is absent.
- [ ] 3.9 Add in-memory and durable SQLite crash-boundary tests for before-decision, decision-before-effect, effect-before-outcome, durable-outcome-before-transition, committed-outcome recovery, terminal intent recovery, one-intent-per-step validation, persisted effect/terminal retry exhaustion, and scope mismatch.

## 4. Research Run Disposition And Latest Isolation

- [ ] 4.1 Add an explicit Research run disposition derived fail-closed from terminal status, quality evidence, matching publication/artifact authority, and identity scope while preserving the existing `save(record)` boundary.
- [ ] 4.2 Update in-memory Research storage so by-run reads retain all diagnostics and latest-by-paper selects accepted records only.
- [ ] 4.3 Implement strict version-1/version-2 filesystem readers that classify v1 records from succeeded status, passing quality, complete identity/checksum-consistent artifact evidence, and unambiguous legacy identity scope without trusting legacy manifest `status` or rewriting v1 bytes; absent, shared-root, or conflicting scope evidence must quarantine.
- [ ] 4.4 Add an expand-then-write deployment gate: ship and verify dual readers first, enable version-2 disposition writes second, and reject rollback targets that cannot read both versions.
- [ ] 4.5 Make mixed-version index creation, repair, concurrent updates, and restart reads select accepted records only; a newer quarantine record must not shadow accepted latest and a failure-only paper must have no accepted latest index.
- [ ] 4.6 Add explicit scoped quarantine/by-run query contracts without exposing quarantined results through normal analysis, reader, ask, or latest endpoints.
- [ ] 4.7 Audit historical failed-run artifact manifests, classify their refs as `legacy_quarantined` without deleting bytes or rewriting old records, and make only an explicit diagnostic reader resolve them.
- [ ] 4.8 Preserve HTTP/MCP/SDK error and trace response shapes while proving returned failed results and post-run-creation worker/handler/terminal exceptions commit scoped quarantine diagnostics and cannot shadow an accepted result after service reconstruction.
- [ ] 4.9 Implement the bounded `ResearchRunDispositionReconciler` for startup and lazy referenced-run recovery after durable terminal publication/`COMPLETE_RUN` but before accepted record save; verify accepted versus quarantine from durable evidence, remain idempotent, and call zero workers/effect handlers.

## 5. Research Artifact Publication Cutover

- [ ] 5.1 Change `publish_artifacts` from direct canonical writes to a typed atomic bundle intent and declare its exact Harness side-effect handler in the paper-analysis workflow.
- [ ] 5.2 Implement a Research preparation handler over the existing run-bound artifact/path/checksum runtime, using hidden candidate paths and a durable `prepared` outcome with zero canonical manifest/index visibility, bounded retention, quarantine-on-cancel/supersession, and owned cleanup.
- [ ] 5.3 Make the atomic group idempotent by effect id, verify every prepared member, and ensure Nth-member failure leaves zero new published refs with owned candidate cleanup/quarantine.
- [ ] 5.4 Merge only hidden candidate refs from the prepared outcome into the workspace; public artifact refs MUST come from the later terminal publication outcome without changing their URI or payload contracts.
- [ ] 5.5 Replace post-success trace/transcript writes with one controller-terminal handler after all step outcomes are durable and before `COMPLETE_RUN`; stage trace/transcript with an explicit committed-history cutoff into the same atomic group, then perform the only finalized-accepted manifest/index visibility commit and durable outcome read-back while keeping the event history as the complete replay source.
- [ ] 5.6 Prove terminal handler failure prevents durable success, recovery reuses the original terminal effect id, version-2 artifact reads require a matching accepted run disposition, and failed/halted/approval-waiting runs retain durable history or scoped quarantine diagnostics with zero canonical main, trace, or transcript visibility.
- [ ] 5.7 Update production Research composition and lifecycle tests so candidate workers cannot access concrete artifact commit ports and only registered worker-originated or controller-terminal handlers own publication.

## 6. Skill Release Authority

- [ ] 6.1 Add a provenance-bound skill release authorization that resolves canonical candidate, held-out evaluation, promotion gate, approval, package hash, release version, rollback plan, and side-effect decision refs.
- [ ] 6.2 Require the release registry to resolve that authorization before mutating releases, history, or active versions; caller-created approved-looking decisions must fail with zero writes.
- [ ] 6.3 Update `FakeSkillEvolutionPort` and the shared release contract suite to use the same authority path while keeping it explicitly non-production.
- [ ] 6.4 Add ordinary-run and adversarial promotion matrices proving active/release writes remain zero without the explicit Harness evolution handler.

## 7. Verification And Delivery

- [ ] 7.1 Run focused worker-result, side-effect registry/control-plane, approval/scope, retry/replan, durable replay/recovery, Research service/store/artifact, terminal publication, skill-evolution, and architecture suites.
- [ ] 7.2 Run broader `tests/framework/harness`, `tests/business/research`, `tests/infrastructure/research`, and `tests/interfaces` compatibility suites with skip/deselection reasons recorded.
- [ ] 7.3 Run `openspec validate harness-side-effect-authority-closure --strict`, `openspec validate --all --strict`, and `git diff --check`.
- [ ] 7.4 Run `.\.venv\Scripts\python.exe -m scripts.dev compile` and mandatory `.\.venv\Scripts\python.exe -m scripts.dev smoke`; fix root causes rather than weakening gates.
- [ ] 7.5 Act as the single accountable completion task for HAR-008 and HAR-009: update `evidence.md` with HAR-008 supporting tasks `1.1/2.1-2.8/3.1-3.8/6.4`, HAR-009 supporting tasks `1.2-1.5/1.7/2.5-2.8/3.2-3.9/4.1-5.7/6.1-6.3`, exact tests, compatibility, migration, rollback, and residual external-service limits; these ranges are evidence links, not additional accountable owners, and this task remains open until every required result is committed or explicitly routed as an unclaimed external-owner dependency.
- [ ] 7.6 Record and enforce archive/deployment order: archive `research-runtime-production-composition` before applying this change's `research-run-persistence` delta, deploy v1/v2 readers before v2 writers, and retain a dual-reader rollback target.
- [ ] 7.7 Stage only change-owned paths and mixed hunks, create an isolated staged-only candidate, repeat applicable gates, commit, and verify no unrelated active OpenSpec or user files are included.
