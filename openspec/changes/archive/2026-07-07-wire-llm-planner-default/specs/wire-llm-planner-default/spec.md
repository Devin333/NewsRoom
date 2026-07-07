## ADDED Requirements

### Requirement: Paper RAG factory keeps deterministic planner disabled by default
The Paper RAG production composition root SHALL leave the RAG plan worker unset unless LLM planner mode is explicitly enabled or an explicit worker is injected.

#### Scenario: Environment flag absent
- **WHEN** `build_paper_rag_session()` is called and `NEWS_RAG_LLM_PLANNER` is unset
- **THEN** the constructed `PaperRAGSession` SHALL receive `plan_worker=None`

#### Scenario: Environment flag false
- **WHEN** `build_paper_rag_session()` is called and `NEWS_RAG_LLM_PLANNER` is set to a false value
- **THEN** the constructed `PaperRAGSession` SHALL receive `plan_worker=None`

### Requirement: Paper RAG factory wires LLM planner when explicitly enabled
The Paper RAG production composition root SHALL construct an LLM-backed `ResearchCandidateWorkerPort` for RAG plan candidates when `NEWS_RAG_LLM_PLANNER` is truthy.

#### Scenario: Environment flag true
- **WHEN** `build_paper_rag_session()` is called and `NEWS_RAG_LLM_PLANNER` is truthy
- **THEN** the constructed `PaperRAGSession` SHALL receive a plan worker compatible with `ResearchCandidateWorkerPort`

#### Scenario: Explicit worker takes precedence
- **WHEN** `build_paper_rag_session(plan_worker=...)` is called and `NEWS_RAG_LLM_PLANNER` is truthy
- **THEN** the constructed `PaperRAGSession` SHALL receive the explicit worker
- **AND** the factory SHALL NOT construct a replacement LLM planner worker

### Requirement: LLM RAG plan worker returns candidate-only JSON payloads
The LLM-backed Research RAG plan worker SHALL request candidate retrieval plans from the LLM and return a dict containing a `candidate` payload for Harness validation.

#### Scenario: Valid planner JSON
- **WHEN** the LLM returns a JSON object containing a `candidate` retrieval plan payload
- **THEN** `generate_candidate(task="rag_plan_candidate", payload=...)` SHALL return that candidate payload

#### Scenario: Invalid planner JSON
- **WHEN** the LLM returns non-JSON or a JSON value that is not an object
- **THEN** `generate_candidate(task="rag_plan_candidate", payload=...)` SHALL fail before Harness executes the candidate
