## ADDED Requirements

### Requirement: Paper analysis uses the final orchestrated sub-agent workflow
The paper radar business layer SHALL provide a paper analysis orchestrator that runs structure, selection, taxonomy, experiment, evidence verification, contribution, quality, reproducibility, comparison, profile composer, and memory agents through a shared workspace.

#### Scenario: Orchestrator writes final workflow roles in order
- **WHEN** a paper analysis request is processed
- **THEN** the workspace contains metadata, source artifacts, semantic sections, selection decision, taxonomy result, experiment result, benchmark claims, evidence verification, contribution result, quality result, reproducibility result, comparison result, final profile, and memory records in workflow order

#### Scenario: Agent events are recorded
- **WHEN** each paper sub-agent starts and completes
- **THEN** the session event log records `agent.started` and `agent.completed`

### Requirement: Paper agents do not own session storage
Paper sub-agents MUST receive `PaperAgentContext` from the orchestrator and return `PaperAgentResult` without directly reading or writing the framework workspace and without calling each other.

#### Scenario: Required roles are read through context
- **WHEN** an agent declares required roles
- **THEN** the orchestrator reads those roles from the workspace and passes them in `PaperAgentContext.shared_items`

### Requirement: Paper final profile is PublicPaper compatible
The profile composer SHALL produce a final profile with top-level `primaryTaskGroup`, `taskRefs`, `methodRefs`, `benchmarks`, `confidence`, `evidenceSummary`, `classification`, `aiSummary`, `lowConfidenceItems`, and review queue metadata.

#### Scenario: Final profile can feed ingest normalization
- **WHEN** ingest receives the final profile from agent analysis
- **THEN** existing normalization can read task refs, method refs, benchmarks, confidence, evidence summary, classification metadata, and AI summary

### Requirement: Paper session data excludes raw full text and sensitive payloads
Paper analysis MUST NOT write raw `full_text`, raw payload fields, tokens, API keys, authorization values, or cookie values into the shared workspace.

#### Scenario: Full text remains outside workspace
- **WHEN** a request includes full paper text
- **THEN** workspace items only contain safe metadata, derived sections, bounded excerpts, digests, and structured agent outputs

### Requirement: Benchmark claims are verified before final profile benchmarks
Experiment extraction SHALL produce benchmark claims and evidence verification SHALL read them before quality and profile composition.

#### Scenario: Evidence verification reads benchmark claims role
- **WHEN** benchmark claims are written to `paper_benchmark_claims`
- **THEN** `PaperEvidenceVerificationAgent` verifies those claims and `PaperQualityAgent` can lower score for weak or rejected claims

### Requirement: External capability gaps degrade with warnings
Paper agents SHALL continue producing structured outputs when optional repository or memory capabilities are unavailable.

#### Scenario: Repository unavailable does not skip reproducibility agent
- **WHEN** no repository URL is available
- **THEN** `PaperReproducibilityAgent` returns a reproducibility result with `repo_unavailable` warning

#### Scenario: Memory unavailable does not skip comparison agent
- **WHEN** MemoryRuntime is not configured
- **THEN** `PaperComparisonAgent` returns a comparison result with `memory_unavailable` warning

### Requirement: Reader adapter can answer from final profile and session evidence
The paper reader adapter SHALL read final profile, session snapshot/evidence, and paper memory when available and return answers with citations.

#### Scenario: Reader answer includes citations
- **WHEN** `PaperReaderAgentAdapter` receives final profile and experiment evidence
- **THEN** it returns `paper_reader_answer` with answer text, evidence, and citations

### Requirement: Agent failures degrade to a best-effort final profile
The orchestrator SHALL capture agent errors and still attempt to produce a final profile from available prior outputs.

#### Scenario: Sub-agent failure does not crash orchestration
- **WHEN** one paper sub-agent raises an exception
- **THEN** the analysis result includes errors and returns a degraded final profile
