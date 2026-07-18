## 1. Regression Baseline

- [x] 1.1 Add registry contract tests for exact id/version resolution, duplicate registrations, ambiguous or unversioned references, missing dependencies, and dependency cycles.
- [x] 1.2 Add a control-plane regression proving an unknown declared gate fails before `RUN_CREATED`/`WORKER_CALLED` and leaves worker call count at zero.
- [x] 1.3 Replace the worker-score routing fixture with a gate-driven route and add a regression proving high worker self-evaluation cannot create or override `HarnessQualityVerdict`.
- [x] 1.4 Add two-step execution tests proving each VERIFY runs framework mandatory gates plus only its declared gate/dependencies in stable de-duplicated order.
- [x] 1.5 Add failure fixtures for gate exceptions, invalid result identity, missing results, and `ON_VERDICT` routing from a step without a declared gate.

## 2. Versioned Gate Runtime

- [x] 2.1 Implement immutable gate references, registrations, bindings, and an instance-scoped `DeterministicGateRegistry` under `framework/harness` without business or infrastructure imports.
- [x] 2.2 Add workflow preflight that binds all declared gate references and rejects invalid routing/gate contracts before run creation or recovery worker execution.
- [x] 2.3 Separate framework mandatory verify gates from the current step's bound domain gate and deterministic dependencies.
- [x] 2.4 Enrich gate results with exact identity/version, deterministic input checksum, stable reason code, and result checksum while preserving the existing safe event envelope.
- [x] 2.5 Implement the deterministic verdict aggregator and remove metadata/worker-output branches from the Harness verdict path.
- [x] 2.6 Migrate worker self-evaluation to observational/domain-specific fields and reject worker output keys that can be interpreted directly as Harness verdict, routing, approval, memory, or publication decisions.
- [x] 2.7 Update public Harness exports and serialization tests while keeping `quality_gate` a string and preserving existing workflow/event envelope shapes.

## 3. Scheduler And Durable Replay

- [x] 3.1 Make scheduler completion, retry, replan, repair, halt, and `ON_VERDICT` routing consume only the aggregated deterministic verdict and required gate results.
- [x] 3.2 Commit canonical gate evidence and aggregate verdict through the existing VERIFY transition, phase event, and deterministic decision history before any downstream transition or publication.
- [x] 3.3 Recover a committed VERIFY from recorded gate evidence and pinned versions; fail with typed history errors on missing evidence, unavailable versions, count mismatches, or checksum conflicts.
- [x] 3.4 Keep incomplete VERIFY re-evaluation restricted to the exact pinned deterministic implementation and prohibit LLM/worker calls during gate recovery.
- [x] 3.5 Add in-memory and durable SQLite recovery/replay tests, including crash boundaries before/after VERIFY commit and a legacy-readable-but-unverified history fixture.

## 4. Research Gate Convergence

- [x] 4.1 Freeze a parameterized inventory of every gate declaration in paper-analysis, paper-RAG, and reader-repair workflows and classify each as executable, renamed/split, precondition-owned, or removed.
- [x] 4.2 Implement Research-owned adapters for the active paper-analysis schema, lineage, context, evidence, summary, claim, quality, reader, paper-card, and benchmark invariants by delegating to existing domain rules.
- [x] 4.3 Remove or redesign misleading declarations such as publication/memory precondition gates so no post-worker VERIFY gate claims to authorize an already completed side effect.
- [x] 4.4 Split semantically conflicting RAG declarations and either connect paper-RAG/reader-repair workflow specs to their real production controllers or delete declarations that have no executable production path.
- [x] 4.5 Compose a versioned Research registry and replace the broad Research `verify_gates` tuple so the active single-paper runtime executes only each step's declared gate.
- [x] 4.6 Add per-gate failure fixtures for active paper analysis and assert the matching durable gate id/version/input reference appears before downstream work.
- [x] 4.7 Add zero-write tests proving failed publication, memory policy, namespace, and source-lineage preconditions do not call fake artifact or memory stores.

## 5. Verification And Delivery

- [x] 5.1 Run Harness control-plane, routing, durable event/replay, and Research workflow focused suites and record exact results in the change evidence.
- [x] 5.2 Run architecture boundary tests and confirm `framework/harness` remains domain-neutral and Research does not gain interfaces/infrastructure/legacy imports.
- [x] 5.3 Run `openspec validate harness-deterministic-gate-enforcement --strict`, `openspec validate --all --strict`, and `python -m scripts.dev compile`.
- [x] 5.4 Run mandatory `python -m scripts.dev smoke`, resolve root causes, and run `git diff --check` before committing the implementation.
- [x] 5.5 Update PRD/OpenSpec status and attach requirements-to-tests, compatibility, replay, migration, and rollback evidence without marking later phase 20 changes complete.
