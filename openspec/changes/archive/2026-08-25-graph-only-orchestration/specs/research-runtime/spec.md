## MODIFIED Requirements

### Requirement: Research Domain Boundary

Research runtime SHALL live under `business/research` and SHALL express Research domain models, ports, use cases, Graph definitions, and business rules. `business/research` MUST NOT import `business/boards/paper_radar`, `interfaces`, concrete `infrastructure` modules, `framework.workflow`, or the retired Harness Workflow namespace.

#### Scenario: Research imports stay inside allowed boundaries

- **WHEN** import boundary tests scan `business/research`
- **THEN** no import may target `business.boards.paper_radar`, `interfaces`, `infrastructure`, `framework.workflow`, or `framework.harness.workflow`
- **AND** Research may depend only on domain-neutral framework contracts and Research-owned Graph modules

### Requirement: Research Product Scenarios Precede Domain Modeling

Research implementation SHALL first define product scenarios for paper card, taxonomy, reader, reading session, code repository, benchmark, method graph, agent intelligence, and Research RAG before domain models and Graph definitions are finalized.

#### Scenario: Domain modeling consumes scenarios

- **WHEN** stage 5 domain modeling begins
- **THEN** the Research product scenario artifact from stage 5A MUST exist
- **AND** Graph definitions and domain models MUST map back to those scenarios rather than old paper_radar payloads

### Requirement: Research Single Paper Loop

Research runtime SHALL support a single-paper analysis loop controlled by Harness Graph. The loop SHALL use Research domain models, Research ports, bounded context, deterministic gates, and fake LLM in tests. Every quality gate declared by the paper-analysis, paper-RAG, and reader-repair Graph definitions MUST resolve to an exact Research-owned deterministic gate implementation and version before the run starts.

#### Scenario: Single paper analysis is Graph-controlled

- **WHEN** a fake LLM returns candidate analysis for one paper
- **THEN** Harness MUST verify the candidate with the exact Research gate declared for the current Graph node before producing a report artifact
- **AND** the LLM result MUST NOT decide routing, memory writes, or publication

#### Scenario: Research Graph declarations are executable

- **WHEN** Research composition loads a paper-analysis, paper-RAG, or reader-repair Graph definition
- **THEN** every declared gate reference MUST have one registered deterministic implementation and committed execution test
- **AND** a name-only metadata gate with no implementation MUST be removed or rejected rather than treated as passed

#### Scenario: Research gate registration is incomplete

- **WHEN** a Research Graph references an unknown or unavailable gate version
- **THEN** Harness MUST reject the run before any Research worker or external source is called
- **AND** no report, reader payload, memory write, or artifact publication may be accepted

#### Scenario: Research prepares an artifact candidate bundle

- **WHEN** the paper-analysis Graph reaches its `publish_artifacts` Function activity after producing verified Research outputs
- **THEN** the activity MAY assemble checksum-bound pending artifact requests and return a worker-origin `HarnessSideEffectIntent`
- **AND** the activity MUST NOT call `ArtifactPort`, commit a terminal manifest, or represent candidate refs as public artifact refs
- **AND** only the exact Artifact handler invoked with controller-terminal authority after all deterministic VERIFY and inherited publication gates pass may publish the bundle and terminal trace artifacts

#### Scenario: Reader repair remains candidate-only until Harness commits memory

- **WHEN** the reader-repair Graph runs its proposer and verifier Subagent activities
- **THEN** the proposer MAY return only a localized repair candidate and the verifier MAY return only source-backed observations without `passed`, verdict, routing, memory-write, publication, or promotion authority
- **AND** exact deterministic gates MUST bind the issue, context, candidate, observations, result, repair case, procedural strategy candidates, and memory candidate to previously verified outputs
- **AND** the Graph MUST use a bounded closed patch-operation schema and an exact `apply_repair_candidate` Function activity that performs only a deterministic in-memory transformation and returns a checksum-bound `ReaderRepairApplicationCandidate` without writing memory, storage, Artifact, or a public ref
- **AND** the verifier MUST bind both the proposed repair and the application candidate while remaining observation-only; it MUST NOT invent an after-payload ref or emit pass/fail fields
- **AND** an exact deterministic application verification gate MUST recompute schema, navigation, target-scope, before/after checksum, and source-lineage checks from the application candidate; worker metadata and natural-language findings MUST NOT establish a quality verdict
- **AND** `build_repair_result` MUST consume the verified application record plus an exact Harness node-output identity/checksum and MUST NOT synthesize a `:repaired` ref, accept an unbound caller ref, or represent a candidate ref as durable/public output
- **AND** application quality failure MUST trigger bounded replan/retry/halt; failed-repair diagnostic memory MAY be committed only under a separate explicit controller-terminal failure policy and MUST NOT bypass a failed deterministic gate
- **AND** the final Function activity MAY return only a proposed `MemoryWriteCandidate` plus a worker-origin side-effect intent for the exact reader-repair memory handler
- **AND** worker-origin preparation MUST perform zero memory writes and MUST expose no public memory refs
- **AND** only controller-terminal authority after deterministic VERIFY may commit episodic or procedural repair memory
- **AND** the terminal handler MUST commit the repair case and its procedural strategies atomically and idempotently, return a checksummed receipt, and expose immutable versioned memory refs
- **AND** a `ReaderRepairSkillCandidateSeed` MUST keep `publishes_skill=false` and may enter only the Harness-controlled skill evolution workflow; the reader-repair Graph MUST NOT bind an active-skill promotion or Artifact publication handler
