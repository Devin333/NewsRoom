## ADDED Requirements

### Requirement: Research exposes an opt-in dynamic analysis workflow variant

Research SHALL provide a dynamic paper-analysis workflow variant with a distinct workflow id/version and a fixed `dynamic_analysis_stage`. The existing `build_paper_analysis_workflow_spec()` SHALL remain available and SHALL remain the default composition path until dynamic parity and replay acceptance complete.

#### Scenario: Static Research workflow remains the default

- **WHEN** an existing caller builds the standard paper-analysis workflow without an explicit dynamic workflow selection
- **THEN** Research MUST return the existing static workflow contract
- **AND** no TaskPlan candidate or dynamic stage may be invoked

#### Scenario: Dynamic workflow is explicitly selected

- **WHEN** a caller selects `build_dynamic_paper_analysis_workflow_spec()` or its pinned workflow id/version
- **THEN** the graph MUST contain one fixed `dynamic_analysis_stage` between `build_evidence_pack` and `verify_claims`
- **AND** the workflow graph checksum and workflow identity MUST identify the dynamic variant distinctly from the static variant

#### Scenario: Dynamic workflow changes after run creation

- **WHEN** Research code or policy changes after a dynamic run records its graph and policy checksums
- **THEN** recovery MUST continue with the pinned compatible versions or fail closed
- **AND** it MUST NOT silently switch the run to the static workflow or a new dynamic definition

### Requirement: Dynamic analysis has a fixed Research stage boundary

The `research.analysis` dynamic stage SHALL consume only the accepted `document` and `evidence_pack` input references and SHALL produce the existing `analysis_branch_refs` aggregate output. It MUST NOT add cross-stage dependencies, skip fixed source/evidence steps, or create publication, side-effect, quality-decision, or memory-promotion tasks.

#### Scenario: Dynamic analysis receives valid inputs

- **WHEN** `document` and `evidence_pack` have passed their existing deterministic gates
- **THEN** the dynamic stage MAY build a TaskPlan whose task context contains those references
- **AND** the stage MUST not copy raw parent messages or unauthorized context into a subagent envelope

#### Scenario: Candidate references an unavailable future output

- **WHEN** a candidate task references `research_quality`, `reader_payload`, or an output from a later fixed step
- **THEN** Research stage validation MUST reject the candidate before dispatch
- **AND** the fixed downstream graph MUST remain unchanged

#### Scenario: Analysis aggregation completes

- **WHEN** accepted task results satisfy every required Research analysis role
- **THEN** the deterministic stage aggregator MUST write `analysis_branch_refs` with stable refs and checksum
- **AND** `verify_claims` MUST consume that aggregate through its existing input contract

### Requirement: Research dynamic tasks have required roles and deterministic gates

The Research dynamic analysis policy SHALL require the output roles `analysis.structure`, `analysis.contribution`, and `analysis.experiments`. It MAY allow additional helper tasks only when they write policy-approved roles and do not create an output conflict. Task results MUST continue to use the existing Research deterministic gate contracts.

#### Scenario: Structure task passes its gate

- **WHEN** a task bound to the structure capability returns an output matching the summary schema and evidence boundary
- **THEN** Harness MUST run the exact Research gate references declared by the stage policy
- **AND** the task may contribute `analysis.structure` to aggregation only after those gates pass

#### Scenario: Experiment task has missing benchmark lineage

- **WHEN** an experiment-analysis result fails `BenchmarkEvidenceLineageGate@1`
- **THEN** the task MUST fail verification or enter a bounded retry/replan path
- **AND** it MUST not be treated as a valid `analysis.experiments` role

#### Scenario: Candidate tries to supply a quality verdict

- **WHEN** a Research task output contains `quality_passed`, `quality_verdict`, or a publication decision
- **THEN** the existing Harness/SubAgent result contract MUST reject the control field
- **AND** `ResearchQualityGate@1` MUST remain the only quality authority

### Requirement: Research worker binding and context remain Harness-controlled

Research dynamic task candidates SHALL use allowlisted Research capability hints that resolve through the registered SubAgentSpec/worker registry. Harness MUST apply existing context isolation, tool allowlist, memory namespace, budget, transcript, and output-schema gates to every dynamic task.

#### Scenario: Research capability resolves to a registered subagent

- **WHEN** a candidate requests an allowlisted Research analysis capability with one compatible binding
- **THEN** Harness MUST create a bounded `SubAgentInvocation` with task input refs and policy-approved context
- **AND** the subagent MUST not receive sibling private history, hidden prompts, or unapproved memory

#### Scenario: Research capability is not registered

- **WHEN** a candidate requests a capability that has no unique registered binding
- **THEN** the dynamic plan MUST be rejected before any subagent invocation
- **AND** Research MUST not fall back to a fake, legacy, or arbitrary worker

### Requirement: Research failure and replan preserve fixed quality and publication boundaries

A Research dynamic task failure MAY retry within its task policy and MAY produce a bounded `PlanPatch` only for pending analysis tasks. The dynamic stage MUST pass deterministic aggregation and `verify_claims` before `ResearchQualityGate@1`, reader payload, paper card, or artifact publication can proceed.

#### Scenario: Failed analysis task receives a replacement

- **WHEN** a task exhausts retry and the Research policy allows a replacement capability
- **THEN** Harness MAY accept a versioned patch that adds a replacement task while preserving completed results
- **AND** the stage MUST re-run required role and aggregation validation before continuing

#### Scenario: Claim verification fails

- **WHEN** `ClaimEvidenceGate@1` fails after dynamic analysis aggregation
- **THEN** the fixed workflow MUST choose its declared deterministic failure or repair path
- **AND** an LLM patch MUST NOT mark claim verification or quality as passed

#### Scenario: Publication is attempted before quality success

- **WHEN** dynamic analysis, claim verification, or `ResearchQualityGate@1` has not produced an accepted success result
- **THEN** `build_reader_payload`, `build_paper_card`, and `publish_artifacts` MUST NOT be activated
- **AND** no artifact publication side effect may be committed

### Requirement: Dynamic Research results remain compatible and replayable

The dynamic workflow SHALL preserve the existing public Research result envelope and downstream artifact contracts, while exposing plan/task references only through authorized inspection and transcript projections. Dynamic runs MUST have independent golden event histories and MUST replay without invoking live LLM, subagent, source, RAG, or publication adapters.

#### Scenario: Dynamic result passes the existing publication path

- **WHEN** dynamic analysis, claim verification, quality gate, reader payload, paper card, and publication all succeed
- **THEN** the returned Research result MUST contain compatible paper, quality, artifact, and trace references
- **AND** plan/task internals MUST remain refs or security-projected metadata rather than raw prompts

#### Scenario: Dynamic run is replayed offline

- **WHEN** a completed dynamic Research run is replayed using its checkpoint and event history
- **THEN** replay MUST reproduce plan version, task terminal states, aggregate refs, gate evidence, and outcome checksums
- **AND** replay MUST not call live external sources, LLMs, subagents, or artifact handlers

#### Scenario: Dynamic run has corrupt plan evidence

- **WHEN** the dynamic plan, patch, task result, or aggregate checksum cannot be verified
- **THEN** Research recovery MUST fail closed with a sanitized typed diagnostic
- **AND** it MUST not publish a report or substitute the static workflow for the corrupted run

### Requirement: Research production composition does not leak dynamic test fakes

The dynamic workflow variant SHALL use the same production Research composition boundary as the static workflow. Fake LLMs, fake subagents, in-memory stores, and fixture-only artifact adapters MAY be used only in explicit tests and MUST NOT become the default HTTP, MCP, CLI, or production application dependencies.

#### Scenario: Production dynamic workflow is composed

- **WHEN** a configured production Research entrypoint selects the dynamic workflow
- **THEN** it MUST resolve the real Harness, worker registry, Research adapters, durable run store, and artifact ports
- **AND** it MUST not silently install a fake or in-memory fallback

#### Scenario: Required dynamic capability is unavailable

- **WHEN** production configuration lacks a required dynamic plan builder, worker binding, or durable store capability
- **THEN** the entrypoint MUST return a stable sanitized unavailable error
- **AND** it MUST not execute an unverified compatibility path or publish partial artifacts
