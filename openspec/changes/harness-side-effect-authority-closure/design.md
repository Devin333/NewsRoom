## Context

The Harness control plane already commits worker activities, deterministic VERIFY evidence, scheduler decisions, bounded state transitions, and recovery history. The archived gate-enforcement change made gate results authoritative, but it intentionally did not add a side-effect commit runtime. Four concrete gaps remain:

- `HarnessWorkerResult` rejects only exact top-level keys in `output`; aliases such as `published`, `promote`, and `release`, nested decision objects, and the other worker-controlled mappings are not covered.
- An effectful worker executes before approval and VERIFY. A failed gate or `waiting_approval` state therefore cannot undo an artifact, memory, tool, or release-store mutation performed inside the worker.
- Research `publish_artifacts` writes multiple canonical artifacts and manifest/index entries during the ARTIFACT worker's EXECUTE phase. Its serialized `publish_requires_verify` terminal policy has no runtime consumer.
- Research run persistence saves halted and quality-failed results into the same latest-by-paper index as accepted results. Diagnostics remain useful by run id, but their current visibility is not isolated from the published/latest read path.

The existing durable event change owns canonical envelopes, event schemas, storage delivery, and replay infrastructure. The Tool governance change owns Tool risk and approval models. This change must consume those boundaries and must not modify `framework/events/schema/catalog.py`, generic `framework/tool`, generic `framework/workflow`, Redis worker queues, OpenAPI, or shared MCP/interface work currently owned elsewhere. Narrow additive changes to Harness decision/history safe projections require an explicit overlap check with `durable-event-runtime`; no event envelope or catalog ownership transfers.

`research-run-persistence` is still introduced by the unarchived `research-runtime-production-composition` change, whose current wording selects the latest committed run. This change explicitly modifies that capability to select the latest accepted run. The Research baseline change must be archived first, or the two changes must be archived in that dependency order, so the delta is never applied without its base requirement.

## Goals / Non-Goals

**Goals:**

- Make every Harness-managed side effect declared through this contract consume a typed candidate intent and an authority decision derived from workflow policy, exact deterministic gate evidence, budgets, and any required durable approval.
- Ensure the authority decision is durable before an effect becomes externally visible and the outcome is durable before step/run success is committed.
- Keep failed, halted, blocked, cancelled, and approval-waiting data queryable as isolated diagnostics without exposing it through canonical/published/latest paths.
- Make recovery finish an authorized incomplete commit at most once and make replay inspect decisions/outcomes without executing workers or effects.
- Cut the real Research artifact, terminal trace/transcript, and run-store paths to the contract and harden the in-memory skill release contract against unbound promotion objects.

**Non-Goals:**

- Replacing the Harness scheduler, PLAN/EXECUTE/VERIFY state machine, gate registry, or durable event runtime.
- Defining Tool risk classification, Tool approval DTO/store semantics, or a production Harness ToolRegistry; those remain in `tool-governance-canonicalization` and the conditional Source-tool composition change.
- Claiming that generic Tool, generic Harness Memory, AgentLoop, Workflow Tool runner, or Reader Repair production effects are integrated merely because their contract fakes pass; each production adapter requires its owning change to declare and bind a handler.
- Implementing Research experience-memory provenance (`RES-007`) or making ordinary Research runs evolve skills.
- Replacing domain-specific Reader Repair memory gates, RAG session bounds, or artifact integrity/path/checksum primitives that already have canonical owners.
- Introducing distributed transactions across external services. Atomicity here means one durable authorization identity, idempotent handler execution, and one published visibility/index commit; hidden orphan candidates may be cleaned safely.

## Decisions

### 1. Workflow steps declare exact side-effect handlers; workers return typed intents only

Add a domain-neutral `HarnessSideEffectIntent` model with stable `effect_id`, `kind`, `origin`, `payload` or integrity-protected candidate refs, `atomic_group`, `identity_scope_ref`, `subject_scope_ref`, and idempotency identity. `origin=worker` binds the intent to an exact run, step, attempt, worker-result ref, and candidate checksum. `origin=controller_terminal` binds it instead to the run, terminal action, current state checksum, and completion-decision input after every step outcome is durable; it cannot carry a worker-result ref. A worker result has zero or one `effect_intent`; a bundle uses one intent with multiple atomic-group members, while multiple kinds or handlers require separate workflow steps. Add an optional exact side-effect handler reference to `HarnessStepSpec`; omit it from serialized output when absent so historic workflow payloads and checksums remain unchanged. A side-effect declaration is resolved through an instance-scoped `HarnessSideEffectRegistry` during the same preflight boundary as deterministic gates.

Controller-terminal handlers are declared through an optional versioned `HarnessTerminalSideEffectPolicy` in the run/workflow terminal-policy projection rather than a synthetic workflow step. The policy pins handler, kind, approval requirement, inherited gate/budget evidence rules, and retry limit; it is omitted when absent so historical workflow serialization/checksums remain unchanged. Unknown handlers, versions, or conflicting policies fail before `RUN_CREATED`. Offline replay of a completed legacy run without this policy remains read-only compatible; live recovery that would need an unrecorded terminal effect fails closed with `terminal_side_effect_policy_missing` rather than inventing a default.

The worker phase remains candidate-only. It can return one worker-originated typed intent per step/attempt, observations, diagnostics, metrics, and candidate artifact refs, but it cannot create controller-terminal intents or receive the registered commit handler or concrete memory/artifact/release store. One intent may describe multiple members of one atomic group; multiple intents, handlers, or effect kinds require separate declared steps/attempts rather than implicit aggregation. Composition and architecture tests enforce that production LLM/subagent/candidate workers do not close over those ports. An exact registered handler is the only production object allowed to turn a declared intent into a canonical side effect.

Alternatives rejected:

- Calling an existing effectful worker and checking it afterward preserves the current irreversible EXECUTE-before-VERIFY defect.
- Inferring side effects only from `worker_type` is too broad: a skill, MCP, memory, or artifact worker can legitimately prepare a candidate without committing it.
- A module-global handler registry creates hidden mutable state and makes recovery depend on import order.

### 2. Worker-result ingress rejects ambiguous executable decisions recursively

Extend the result contract with an optional singular `effect_intent` field and one recursive reserved-key validator for the supported untyped worker-controlled `output`, `diagnostics`, and `metrics` mappings. A versioned `FORBIDDEN_WORKER_DECISION_PATHS` snapshot freezes the exact aliases and traversed channels; direct or nested aliases for route, verdict, approval/authorization, memory commit, publication, active release, or promotion are rejected with a stable code and sorted field paths. Explicit `*_observation` fields remain legal. Once a value has been parsed into a typed intent, its domain payload is validated by the registered intent schema and is opaque to the authority algorithm: decision-shaped domain keys inside that payload cannot grant authorization. Multiple intents or a handler/kind mismatch are rejected before scheduling or handler invocation.

`artifacts` continues to mean candidate reference strings supplied by a worker. That channel receives strict reference/type validation rather than recursive decision-key interpretation, and a candidate reference is not promoted to an accepted artifact ref merely because it appears in a successful worker result. Legacy ambiguous fields such as bare `published`, `promote`, or `release` are an intentional internal contract break and migrate to `publication_observation`, `promotion_observation`, or typed intents.

Alternatives rejected:

- Expanding only the flat forbidden-key set leaves nested and alternate ingress paths open.
- Silently dropping decision-shaped values hides producer defects and makes recorded activity differ from what the caller believes it submitted.

### 3. Existing durable decisions and transitions form the commit protocol

The scheduler's recorded `COMPLETE_STEP` or terminal completion decision is enriched with a canonical `HarnessSideEffectDecision` projection containing origin, effect id, identity/subject scope refs, exact handler reference, worker-result or terminal-state input ref, gate input/result refs, aggregate verdict ref, approval evidence or explicit versioned `not_required` policy evidence, budget snapshot, effect-attempt counter, atomic group, and stable idempotency key. That existing decision/history record is committed before any handler call.

Keep the strict `HARNESS_DECISION_INPUT_SCHEMA` top-level field set unchanged. The optional handler reference and intent/approval checksums live in the existing current-step or terminal-policy/state sub-projections; the semantic decision and durable safe-payload projections add only exact side-effect refs and status codes. Historical v1 inputs without these optional nested refs retain their existing meaning. The raw candidate remains in the secure recorded activity store, while canonical history contains only bounded non-sensitive refs.

`HarnessControlPlane._complete_step()` then invokes only the bound handler with the recorded authorization. Before returning, the handler/store MUST durably persist an idempotent typed `HarnessSideEffectOutcome`; Harness performs a scoped read-back and verifies its decision, effect, handler, idempotency, disposition, and checksum identity. Only then may the existing `STEP_SUCCESS` transition reference that outcome and become durable. A handler return that cannot be read back is not a committed outcome and cannot advance the step. Controller-terminal effects follow the same protocol before `COMPLETE_RUN`; terminal failure/quarantine decisions use the matching recorded disposition. No new canonical event type, event envelope, schema catalog, or parallel transcript is introduced.

Recovery first scans committed decision history after the last state transition for one dangling `COMPLETE_STEP` or controller-terminal authorization whose run, step or terminal action, origin, identity/subject scope, state checksum, command ordinal, causation, intent, handler, approval, budget, attempt, and decision refs match the current projection. A match is reused; Harness MUST NOT ask the scheduler to create a new ordinal. Conflicting or multiple matches fail closed. Effect attempts consume the existing persisted per-step retry limit; controller-terminal attempts use a dedicated persisted counter capped by the versioned terminal policy's limit, which cannot exceed the run retry budget. Restart never resets either counter. Exhaustion records `effect_retry_exhausted` and reaches one stable non-success terminal state. This reconciliation and the additive safe projection are covered by legacy-history dual-read tests and are coordinated with the durable-event owner.

On recovery:

- a decision with no resolvable outcome may call the idempotent handler with the same effect id and scope refs only when its persisted effect-attempt budget remains;
- a durably persisted matching outcome is reused and the handler is not called;
- mismatched intent, handler, gate, approval, decision, or outcome identity fails closed;
- offline replay reads the recorded decision/outcome and never calls a worker, handler, memory port, artifact publisher, Tool adapter, or release store, even when an outcome is absent.

Alternatives rejected:

- Publishing first and writing an audit event afterward leaves an unrecorded crash window.
- Adding side-effect event tables or changing the canonical event schema violates the active durable-event owner.

### 4. Authorization is fail-closed and effect-specific

A worker-originated side-effect decision is authorized only when the current worker activity completed, all required VERIFY gates passed, the current attempt remains within budget, the workflow declares the exact handler/kind, and any step policy requiring approval resolves through an injected read-only approval-evidence port to a durable approval bound to the same run, step, attempt, effect id, candidate checksum, identity scope, subject scope, and decision version. A controller-terminal decision is authorized only after every step outcome is durable and the current state, completion input, terminal policy, scope refs, handler identity, inherited aggregate gate refs, current budget snapshot/effect-attempt allowance, and approval evidence all match. A terminal policy that does not require approval records a pinned `not_required` policy evidence ref rather than omitting the field. Worker status or worker output cannot create either decision.

Candidate preparation may occur before approval because it is isolated and non-effectful. `resume_after_approval()` accepts an additive opaque approval ref for effectful steps and records the resolved evidence ref in the existing approval decision/transition; a boolean alone is insufficient for an effectful commit. The commit handler cannot run while the state is `waiting_approval`; cancellation quarantines the candidate. Retry and replan produce new attempt/effect identities, so an approval from an earlier attempt cannot authorize a later candidate. `identity_scope_ref` binds the existing Harness tenant scope, while `subject_scope_ref` binds the target actor/resource/namespace without placing raw sensitive identifiers in canonical history; handler/store lookup and approval resolution fail closed on either mismatch.

Tool-specific allowlists and approval records remain external deterministic inputs. This change provides the Harness commit boundary but does not duplicate the Tool policy algorithm.

### 5. Candidate, prepared, quarantine, accepted, and latest are separate visibility states

The canonical disposition vocabulary is `candidate`, `prepared`, `quarantine`, and `accepted`. `candidate` is unverified worker output; `prepared` is a post-VERIFY, checksum-verified hidden effect outcome that is still non-public; `quarantine` is a terminal diagnostic disposition; `accepted` is the only disposition eligible for canonical/published readers and latest indexes. The side-effect port exposes idempotent operations to prepare, accept/publish, quarantine, and read disposition. Prepared records have a bounded retention lease: terminal publication consumes them into accepted, terminal failure/cancel/retry supersession quarantines them, and owned cleanup may remove expired bytes only after durable disposition/history refs remain. Prepared and quarantined records are queryable only through explicit scoped diagnostic readers.

For Research run storage, preserve the existing `save(record)` call shape and by-run diagnostics. Write version-2 record/index schemas with an explicit disposition derived fail-closed from terminal status, quality verdict, publication authorization evidence, and finalized manifest identity. Readers support strict version-1 and version-2 decoding; version-1 bytes are never rewritten. `get_latest_by_paper_id()`, accepted-first ordering from `list_by_paper_id()`, and mixed-version index repair consider accepted records only. A version-1 record is classified on read from its stored result: only `succeeded` plus a passed quality result, a complete identity/checksum-consistent artifact set, and an unambiguous legacy identity scope is accepted. Manifests created by the current legacy Research publisher and never finalized retain `status=running`; that status is not acceptance evidence. The scope may be derived only from validated stored actor metadata or an immutable single-scope storage-root binding. Shared-root, absent, or conflicting scope evidence is quarantined. Deployment is expand-then-write (dual reader first, v2 writer second), and rollback is permitted only to a reader-capable build.

Historical failed runs may already have canonical Research manifest entries from the old sequential publisher. The migration reader correlates run disposition with manifest identity and marks those refs `legacy_quarantined`; normal Research artifact resolution rejects them, while an explicit diagnostic reader can inspect them. For version-2 records, normal Research artifact resolution requires both a finalized manifest and a matching accepted run disposition; a finalized manifest with a missing or quarantined run record remains non-public until deterministic recovery reconciles the run. The migration does not delete bytes or rewrite the historical run record.

The Research application boundary also covers failures that raise after durable Harness run creation but before `ResearchAnalysisResult` returns. It resolves the recorded Harness state/history and any candidate publication disposition, commits a validated quarantine run record, and only then maps the failure to the existing typed service error. Invalid requests that never create a durable run do not fabricate a record. This prevents handler, Nth-artifact, or terminal-publication exceptions from leaving durable Harness evidence with no corresponding by-run diagnostic.

A deterministic `ResearchRunDispositionReconciler` owns the hard-crash window after terminal publication/`COMPLETE_RUN` but before the application service saves the accepted record. Production composition runs bounded reconciliation at startup and normal by-run/artifact reads invoke it lazily for a referenced missing disposition. It reconstructs an accepted record only from a succeeded terminal transition, matching quality/gate/publication outcome, finalized manifest, and identity scope; otherwise it records quarantine. Reconciliation is idempotent, does not rerun workers/effects, and prevents a finalized manifest from remaining permanently invisible after restart.

Alternatives rejected:

- Not saving failed runs loses trace and terminal diagnostics.
- Saving only returned `ResearchAnalysisResult` values misses worker or handler exceptions after durable run creation.
- Keeping one latest index and filtering only in the service still lets other store consumers observe the wrong canonical record.
- Reusing event-schema quarantine tables conflates event migration failures with valid but unaccepted business run outputs.

### 6. Research artifact publication becomes one terminal manifest-visibility transaction

Change the Research ARTIFACT step to prepare a typed bundle intent instead of calling `write_artifact()` during EXECUTE. Its post-VERIFY handler writes content to hidden run-scoped candidate paths, verifies every checksum, and durably records a `prepared` outcome bound to the bundle atomic group; it does not create a canonical manifest/index entry. A failure while writing the Nth candidate leaves no new published visibility; hidden files are quarantined or removed by owned-temp cleanup.

The prepared outcome supplies hidden candidate refs that are merged into the workspace but are not public artifact refs. Trace and transcript become one `origin=controller_terminal` side-effect intent after all step outcomes are durable but before `COMPLETE_RUN` is committed. Its handler reads the committed event history through the terminal authorization cutoff, stages both diagnostic artifacts under the same run, scope, and atomic group, verifies every prepared member, and atomically commits one finalized accepted manifest/index visibility update for the entire group. The terminal artifact records its cutoff ref; the durable event history remains the canonical complete replay source and supplies the later terminal outcome/`COMPLETE_RUN` transition, avoiding a self-referential checksum. The handler then durably records the publication outcome; the terminal success transition may reference public refs only after read-back verification. A failed terminal publication prevents durable run success and leaves zero new normal-reader-visible refs rather than a partial successful run. Failed or halted runs still retain their durable event history and scoped quarantine diagnostics, but do not receive canonical success artifacts. Existing artifact URI, payload, checksum, and manifest reader contracts stay stable after publication.

Alternatives rejected:

- Publishing the main artifact bundle at step completion and adding trace/transcript later still exposes a partial successful-run set when the terminal handler fails.
- Sequentially writing canonical files and appending the manifest at each write exposes a partial publication set.
- Duplicating `ArtifactManager` path/checksum logic inside Harness creates a second artifact runtime.

### 7. Active skill publication resolves authority provenance from the store

`VersionedSkillReleaseRegistry` remains an in-memory contract implementation, not a claimed production composition. Its active-version mutation is tightened to require a side-effect decision reference that resolves to the same candidate, held-out evaluation, deterministic promotion gates, approval (when required), release version, package hash, and rollback-plan ref. The registry does not trust a caller-created `SkillPromotionDecision` object by itself.

`FakeSkillEvolutionPort` is updated to exercise the same contract suite. Ordinary Harness/business runs have no release handler binding and cannot activate a version. A future production release store must implement the same decision-resolution contract rather than treating the fake registry as production-ready.

Alternatives rejected:

- Relying on `decided_by="harness"` in a freely constructed dataclass is provenance by assertion.
- Wiring skill promotion into ordinary Research runs violates the memory-consolidation and held-out-evaluation lifecycle.

## Risks / Trade-offs

- [Recursive field rejection breaks legitimate domain payloads using ambiguous keys] -> provide explicit observation names and typed intent payloads, freeze the exact reserved path matrix, and keep domain facts such as `published_at` legal.
- [A candidate worker still performs hidden I/O] -> remove concrete effect ports from worker composition, add object-graph/closure architecture tests for production handlers, and treat undeclared effectful worker implementations as a contract violation.
- [Crash after external effect but before outcome commit] -> require stable effect ids and handler/store idempotency; recovery reuses the same key and verifies the returned outcome identity.
- [Tenant or namespace scope is confused across retries or readers] -> bind both the Harness identity scope and effect subject scope into intent, approval, decision, outcome, handler lookup, and idempotency; keep raw sensitive values outside canonical history.
- [Filesystem cannot atomically rename many public files] -> stage immutable candidates first and make one atomic manifest/index pointer the visibility commit; orphan candidates are not published and can be cleaned safely.
- [Historical failed Research records currently selected as latest change read behavior] -> preserve by-run access, classify them as quarantine without rewriting, and add accepted-then-failed compatibility regressions.
- [Side-effect evidence enlarges transition/history payloads] -> persist checksums, exact refs, status, and stable reason codes in canonical projections while keeping raw payloads in the existing secure activity/candidate store.
- [Version-2 Research records are unreadable by the old strict reader] -> deploy dual-read before enabling v2 writes, test mixed v1/v2 index repair, and allow rollback only to a build that retains the dual reader.
- [Historical failed runs already exposed artifact manifests] -> build a non-destructive disposition/manifest audit and make normal Research readers reject `legacy_quarantined` refs; retain scoped diagnostic access and record counts in evidence.
- [New work overlaps active Tool/Event/Workflow changes] -> restrict implementation to clean `framework/harness`, Research runtime/store/service, and their tests; consume existing ports and event history without editing those owners.

## Migration Plan

1. Record pre-fix probes for nested/alternate forged decisions, approval-pending and gate-failed write counts, Research accepted-then-failed latest selection, and partial artifact publication.
2. Add origin- and scope-bound typed intent/decision/outcome models, recursive worker ingress validation, exact handler registry, and focused fake ports without changing the durable event schema.
3. Add effect-bound approval evidence resolution, bounded side-effect refs in the existing decision projections, and dangling-decision reconciliation without changing the top-level decision-input schema; retain old-history replay.
4. Integrate decision-before-effect, durable outcome read-back, and outcome-before-success into the existing complete/terminal transitions, then add crash-boundary and offline replay tests.
5. Cut Research artifact preparation to a worker-originated atomic-group intent and move the only manifest/index visibility commit, including trace/transcript, into a controller-terminal intent; add candidate/quarantine cleanup and atomic failure injection.
6. Deploy strict v1/v2 Research readers, then enable v2 disposition writes, accepted-only mixed-version index repair, historical manifest quarantine, and explicit scoped diagnostic reads.
7. Bind skill release activation to resolved authority provenance and keep ordinary-run promotion count at zero.
8. Run focused Harness/Research/skill/artifact/store suites, architecture tests, compile, mandatory smoke, strict OpenSpec validation, and staged-only verification before committing.

Rollback may restore the previous code version while retaining additive disposition/decision readers and all already written accepted or quarantine records. It must not restore pre-VERIFY canonical publication, let failed records replace accepted latest, trust worker decision fields, or publish an active skill from an unbound caller object.

## Open Questions

None for implementation start. A production multi-host side-effect coordinator and production skill-release store require separate changes after the single-host contract is proven.
