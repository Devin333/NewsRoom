## MODIFIED Requirements

### Requirement: Dynamic analysis has a fixed Research stage boundary

The `research.analysis` dynamic stage SHALL consume only the accepted `document` and `evidence_pack` input references and SHALL produce the existing `analysis_branch_refs` aggregate output. It MUST dispatch only policy-approved analysis tasks through the Harness group/wave coordinator, MUST NOT add cross-stage dependencies, skip fixed source/evidence steps, or create publication, side-effect, quality-decision, or memory-promotion tasks.

#### Scenario: Dynamic analysis receives valid inputs

- **WHEN** `document` and `evidence_pack` have passed their existing deterministic gates
- **THEN** the dynamic stage MAY build an immutable TaskPlan whose task context contains those references
- **AND** the stage MUST be able to submit independent analysis tasks as one bounded DispatchGroup without copying raw parent messages or unauthorized context into a subagent envelope

#### Scenario: Candidate references an unavailable future output

- **WHEN** a candidate task references `research_quality`, `reader_payload`, or an output from a later fixed step
- **THEN** Research stage validation MUST reject the candidate before group admission
- **AND** the fixed downstream graph MUST remain unchanged

#### Scenario: Analysis aggregation completes

- **WHEN** accepted task results from a joined DispatchGroup satisfy every required Research analysis role
- **THEN** the deterministic stage aggregator MUST write `analysis_branch_refs` with stable refs and checksum
- **AND** `verify_claims` MUST consume that aggregate through its existing input contract

#### Scenario: Group attempts to bypass the stage boundary

- **WHEN** a dynamic group contains a publication, quality verdict, memory promotion, or outer-Graph routing task
- **THEN** Harness MUST reject the group before child dispatch
- **AND** no fixed successor or publication side effect may be activated

### Requirement: Research dynamic tasks have required roles and deterministic gates

The Research dynamic analysis policy SHALL require the output roles `analysis.structure`, `analysis.contribution`, and `analysis.experiments`. It MAY allow additional helper tasks only when they write policy-approved roles and do not create an output conflict. Independent role tasks MUST be eligible for bounded parallel dispatch, and when concurrency conditions are met Harness MUST dispatch them concurrently. Every task result MUST continue to use the existing Research deterministic gate contracts and the DispatchGroup join MUST require a complete role set across all waves.

#### Scenario: Structure and contribution tasks run in parallel

- **WHEN** the structure and contribution tasks have valid independent inputs, bindings, reservations, and read-only side-effect classes
- **THEN** when both tasks pass concurrency checks, effective parallelism is at least two, and serial fallback is not selected, Harness MUST dispatch them concurrently within the Research policy `max_parallelism`
- **AND** each task MUST pass its own deterministic gate before the role is eligible for aggregation

#### Scenario: Structure task passes its gate

- **WHEN** a task bound to the structure capability returns an output matching the summary schema and evidence boundary
- **THEN** Harness MUST run the exact Research gate references declared by the stage policy
- **AND** the task may contribute `analysis.structure` to aggregation only after those gates pass

#### Scenario: Experiment task has missing benchmark lineage

- **WHEN** an experiment-analysis result fails `BenchmarkEvidenceLineageGate@1`
- **THEN** the task MUST fail verification or enter a bounded retry/replan path
- **AND** it must not be treated as a valid `analysis.experiments` role or successful group contribution

#### Scenario: Candidate tries to supply a quality verdict

- **WHEN** a Research task output contains `quality_passed`, `quality_verdict`, or a publication decision
- **THEN** the existing Harness/SubAgent result contract MUST reject the control field
- **AND** `ResearchQualityGate@1` MUST remain the only quality authority

### Requirement: Research worker binding and context remain Harness-controlled

Research dynamic task candidates SHALL use allowlisted Research capability hints that resolve through the registered SubAgentSpec/worker registry and the Harness `ChildAgentSupervisor` adapter. Harness MUST apply existing context isolation, tool allowlist, memory namespace, budget, transcript, output-schema, lease, and attempt gates to every dynamic task and MUST not share sibling private history. One logical analysis join MUST use one `DispatchGroup`; capacity-limited physical executions MUST use one or more `DispatchWave` records in that group.

#### Scenario: Research capability resolves to a registered subagent

- **WHEN** a candidate requests an allowlisted Research analysis capability with one compatible binding and the group has capacity
- **THEN** Harness MUST create a bounded `SubAgentInvocation` for that task with input refs and policy-approved context
- **AND** the subagent MUST not receive sibling private history, hidden prompts, or unapproved memory

#### Scenario: Research capability is not registered

- **WHEN** a candidate requests a capability that has no unique registered binding
- **THEN** the dynamic plan MUST be rejected before group admission or subagent invocation
- **AND** Research MUST not fall back to a fake, legacy, or arbitrary worker

#### Scenario: Research child lease expires

- **WHEN** a Research child has no verifiable terminal receipt after its supervisor lease expires
- **THEN** the Harness recovery policy MUST mark it indeterminate or create one bounded reclaim/retry outcome
- **AND** the stage MUST not aggregate the child as successful

### Requirement: Research failure and replan preserve fixed quality and publication boundaries

A Research dynamic task failure MAY retry within its task policy and MAY produce a bounded `PlanPatch`. `ADD_REPLACEMENT_TASK` MAY target only a terminal failed logical task; `SKIP_PENDING_TASK` and `UPDATE_PENDING_DEPENDENCY` MAY target only tasks not admitted to any wave. Every replan MUST create a new plan version and DispatchGroup. Research dynamic uses pinned `wait_all` only; it MUST NOT opt into `fail_fast`. The dynamic stage MUST pass deterministic task verification, complete role aggregation, and `verify_claims` before `ResearchQualityGate@1`, reader payload, paper card, or artifact publication can proceed.

#### Scenario: Failed analysis task receives a replacement

- **WHEN** a task exhausts retry and the Research policy allows a replacement capability
- **THEN** Harness MAY accept a versioned `ADD_REPLACEMENT_TASK` patch targeting that terminal failed logical task while preserving completed sibling result refs
- **AND** the new plan version MUST create a new DispatchGroup and the stage MUST re-run required role, group join, and aggregation validation before continuing

#### Scenario: One required role fails under wait-all

- **WHEN** a required role remains failed after bounded attempts and the group join policy is `wait_all`
- **THEN** the dynamic stage MUST return a typed partial-failure outcome without `analysis_branch_refs` success
- **AND** no downstream quality or publication step may be activated

#### Scenario: Claim verification fails

- **WHEN** `ClaimEvidenceGate@1` fails after dynamic analysis aggregation
- **THEN** the fixed workflow MUST choose its declared deterministic failure or repair path
- **AND** an LLM patch MUST NOT mark claim verification or quality as passed

#### Scenario: Publication is attempted before quality success

- **WHEN** dynamic analysis, claim verification, or `ResearchQualityGate@1` has not produced an accepted success result
- **THEN** `build_reader_payload`, `build_paper_card`, and `publish_artifacts` MUST NOT be activated
- **AND** no artifact publication side effect may be committed

### Requirement: Dynamic Research results remain compatible and replayable

The dynamic workflow SHALL preserve the existing public Research result envelope and downstream artifact contracts, while exposing plan/task/group/wave references only through authorized inspection and transcript projections. Dynamic runs MUST have independent golden event histories and MUST replay without invoking live LLM, subagent, source, RAG, tool, supervisor, or publication adapters.

#### Scenario: Dynamic result passes the existing publication path

- **WHEN** dynamic analysis group join, claim verification, quality gate, reader payload, paper card, and publication all succeed
- **THEN** the returned Research result MUST contain compatible paper, quality, artifact, and trace references
- **AND** plan/task/group/wave internals MUST remain refs or security-projected metadata rather than raw prompts

#### Scenario: Dynamic run is replayed offline

- **WHEN** a completed dynamic Research run is replayed using its checkpoint and event history
- **THEN** replay MUST reproduce plan version, group/wave/task terminal states, aggregate refs, gate evidence, and outcome checksums
- **AND** replay MUST not call live external sources, LLMs, subagents, tools, supervisor, or artifact handlers

#### Scenario: Dynamic run has corrupt plan evidence

- **WHEN** the dynamic plan, group, wave, patch, task result, child receipt, or aggregate checksum cannot be verified
- **THEN** Research recovery MUST fail closed with a sanitized typed diagnostic
- **AND** it MUST not publish a report or substitute the static workflow for the corrupted run

### Requirement: Research production composition does not leak dynamic test fakes

The dynamic workflow variant SHALL use the same production Research composition boundary as the static workflow, with a real group/wave coordinator, `ChildAgentSupervisor`, worker registry, durable run/event store, artifact verifier, and authorized tool ports. Fake LLMs, fake subagents, in-memory stores, and fixture-only artifact adapters MAY be used only in explicit tests and MUST NOT become the default HTTP, MCP, CLI, or production application dependencies.

#### Scenario: Production dynamic workflow is composed

- **WHEN** a configured production Research entrypoint selects the dynamic workflow
- **THEN** it MUST resolve the real Harness group/wave coordinator, worker registry, child supervisor, Research adapters, durable run store, artifact ports, and tool ports
- **AND** it MUST not silently install a fake or in-memory fallback

#### Scenario: Required dynamic capability is unavailable

- **WHEN** production configuration lacks a required dynamic plan builder, wave adapter, worker binding, child supervisor, or durable store capability
- **THEN** the entrypoint MUST return a stable sanitized unavailable error unless the pinned policy explicitly allows serial fallback
- **AND** it MUST not execute an unverified compatibility path or publish partial artifacts
