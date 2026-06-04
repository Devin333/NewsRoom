## 0. Stage 0 OpenSpec And Audit

- [x] 0.1 Create `harness-research-runtime` proposal, design, task list, and capability specs.
- [x] 0.2 Audit `framework`, `business`, `interfaces`, `tests`, `openspec/specs`, and `docs/architecture`.
- [x] 0.3 Write `docs/prd/harness-research-runtime/audit-inventory.md` with keep/adapt/delete rows, replacements, deletion phases, and test actions.
- [x] 0.4 Validate the OpenSpec change with `openspec validate harness-research-runtime --strict`.
- [x] 0.5 Run `python -m scripts.dev compile` and record unrelated pre-existing failures if any.
- [x] 0.6 Commit stage 0 documentation and audit changes.

## 1. Stage 1 Framework Harness Contracts

- [x] 1.1 Create `framework/harness` package structure and public contract exports.
- [x] 1.2 Define Harness run, step, phase, policy, budget, decision, gate, and transcript models.
- [x] 1.3 Define Harness port protocols for LLM, tools, memory, skills, artifacts, events, workers, governance, subagents, context, and RAG.
- [x] 1.4 Add focused tests under `tests/framework/harness` for contract construction and import boundaries.
- [x] 1.5 Validate OpenSpec and run compile/tests for the changed surface.

## 2. Stage 2 State Machine And Scheduler

- [x] 2.1 Implement bounded `PLAN -> EXECUTE -> VERIFY` state transitions.
- [x] 2.2 Implement scheduler decisions for `replan`, `retry`, `route_to_repair`, `wait_for_approval`, `halted`, and `failed`.
- [x] 2.3 Implement retry, replan, turn, and worker-call budget enforcement.
- [x] 2.4 Record phase transition events through Harness event ports.
- [x] 2.5 Add deterministic state machine and scheduler tests.

## 3. Stage 3 Seven-Layer Ports

- [ ] 3.1 Implement fake in-memory port implementations for tests.
- [ ] 3.2 Adapt existing `framework/llm`, `framework/tool`, `framework/memory`, `framework/skills`, `framework/artifacts`, `framework/events`, `framework/workers`, and `framework/governance` behind Harness ports.
- [ ] 3.3 Add contract tests proving concrete infrastructure adapters are not imported by Harness contracts.
- [ ] 3.4 Add port replacement tests using fake implementations.

## 4. Stage 3C Subagent Isolation

- [ ] 4.1 Define subagent identity, private history, tool allowlist, memory namespace, transcript, and handoff contracts.
- [ ] 4.2 Implement Harness-approved handoff validation and schema gates.
- [ ] 4.3 Adapt generic `framework/agent/subagents` pieces that are domain-neutral.
- [ ] 4.4 Mark or remove paper-specific subagent code in the cleanup inventory for stage 8.
- [ ] 4.5 Add tests for sibling isolation and denied unauthorized namespace/tool access.

## 5. Stage 3D Context Engineering

- [ ] 5.1 Define six-part `ContextEnvelope` assembly with stable prefix and dynamic tail.
- [ ] 5.2 Implement context budget accounting and five-level compression chain.
- [ ] 5.3 Preserve policy, route table, schemas, gates, allowlists, namespaces, source refs, and budgets from lossy compression.
- [ ] 5.4 Add context snapshot and replay constraints.
- [ ] 5.5 Add tests for stable prefix preservation and dynamic tail compression.

## 6. Stage 3B Bounded Agentic RAG

- [ ] 6.1 Define RAG plan, query, source read, evidence summary, gap, and `RAGContextPack` models.
- [ ] 6.2 Implement Harness-controlled retrieval, read, verify, gap-fill, and stop conditions.
- [ ] 6.3 Enforce `max_rounds`, `max_queries`, `max_source_reads`, `max_memory_hits`, and context budgets.
- [ ] 6.4 Connect RAG context packs to context engineering without placing dynamic results in stable prefix.
- [ ] 6.5 Add bounded RAG tests with fake retrieval and memory ports.

## 7. Stage 3A Skill Evolution

- [ ] 7.1 Define skill candidate repository, validation result, eval result, promotion decision, versioned release, and rollback models.
- [ ] 7.2 Reuse `framework/skills/package`, `framework/skills/runtime`, `framework/skills/validation`, `framework/skills/quality`, and `framework/skills/evaluation` through Harness ports.
- [ ] 7.3 Implement candidate validation, held-out eval replay, promotion, release, and rollback gates.
- [ ] 7.4 Ensure LLM optimizers can only propose candidates or patches and cannot mutate active skill packages.
- [ ] 7.5 Add tests for invalid candidates, failed evals, successful promotion, and rollback.

## 8. Stage 4 Trace Checkpoint Replay

- [ ] 8.1 Implement durable transcript and event log writers for Harness runs.
- [ ] 8.2 Implement checkpoint creation and restoration for Harness state.
- [ ] 8.3 Implement replay readers that expose phase, worker, gate, budget, handoff, RAG, memory intent, and artifact decision events.
- [ ] 8.4 Add replay tests that do not call LLMs or external tools.

## 9. Stage 5A Research Product Scenarios

- [ ] 9.1 Document Research product scenarios for paper card, taxonomy, reader, reading session, code repository, benchmark, method graph, agent intelligence, and RAG.
- [ ] 9.2 Map each scenario to domain model candidates and user-visible backend outcomes.
- [ ] 9.3 Confirm scenarios do not depend on old paper_radar payloads or UI compatibility.

## 10. Stage 5 Research Domain Modeling

- [ ] 10.1 Create `business/research` package structure and domain exports.
- [ ] 10.2 Implement Research models, value objects, ports, services, and workflow specs from stage 5A scenarios.
- [ ] 10.3 Add import boundary tests forbidding `business/boards/paper_radar`, `interfaces`, and concrete `infrastructure` imports.
- [ ] 10.4 Add unit tests for Research business rules and model invariants.

## 11. Stage 6 Research Single Paper Loop

- [ ] 11.1 Implement Harness-controlled single-paper analysis workflow using Research models and fake LLM tests.
- [ ] 11.2 Add deterministic gates for schema, evidence refs, taxonomy, score ranges, and report readiness.
- [ ] 11.3 Persist artifacts through Harness artifact ports.
- [ ] 11.4 Add end-to-end tests for successful, repair-routed, and halted single-paper runs.

## 12. Stage 6A Reader Repair Memory

- [ ] 12.1 Implement reader repair memory models and ports under `business/research/reader_repair`.
- [ ] 12.2 Route repair outcomes to memory first, not active skill mutation.
- [ ] 12.3 Connect consolidated repair strategies to skill evolution candidate generation.
- [ ] 12.4 Add tests proving ordinary repair runs cannot publish skill changes.

## 13. Stage 7 Research Backend Interface

- [ ] 13.1 Create `interfaces/services/research_service.py` as the Research application service entry.
- [ ] 13.2 Create `interfaces/api/routers/research.py` and register Research API routes.
- [ ] 13.3 Ensure Research service does not reuse old `PapersApplicationService`, old paper cache payloads, or `interfaces/api/routers/papers.py`.
- [ ] 13.4 Add service and API tests under `tests/interfaces/research`.

## 14. Stage 8 Framework Cleanup

- [ ] 14.1 Adapt or delete obsolete framework control-flow assets according to `audit-inventory.md`.
- [ ] 14.2 Remove paper-specific code from framework packages.
- [ ] 14.3 Replace legacy framework tests with Harness tests where behavior moved.
- [ ] 14.4 Run full compile, targeted tests, and OpenSpec validation.

## 15. Stage 9 Legacy Business And Test Deletion

- [ ] 15.1 Delete old business modules that no longer serve Harness + Research.
- [ ] 15.2 Delete old paper services, paper API routes, old worker queue bindings, and compatibility adapters replaced by Research.
- [ ] 15.3 Delete or replace old paper/board tests only when old behavior is explicitly deprecated and Research coverage exists.
- [ ] 15.4 Run `openspec validate harness-research-runtime --strict`, `python -m scripts.dev compile`, `python -m scripts.dev test`, and `python -m scripts.dev smoke`.
- [ ] 15.5 Archive the OpenSpec change after all stages are complete.
