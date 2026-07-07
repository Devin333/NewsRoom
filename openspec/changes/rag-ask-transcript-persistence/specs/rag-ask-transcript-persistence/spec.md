## ADDED Requirements

### Requirement: Gated Paper RAG ask persists its transcript
The Paper RAG service SHALL persist the bounded RAG transcript for every gated generated `rag_ask` response.

#### Scenario: Gated ask completes
- **WHEN** `PaperRagApplicationService.rag_ask()` is called with `generate=True`
- **THEN** the service SHALL write the session transcript to local transcript storage
- **AND** the response SHALL include a transcript artifact reference that identifies the stored transcript

#### Scenario: Retrieve-only ask does not persist a transcript
- **WHEN** `PaperRagApplicationService.rag_ask()` is called with `generate=False`
- **THEN** the service SHALL NOT write a transcript artifact
- **AND** the response SHALL retain the existing retrieve-only payload shape

### Requirement: Persisted transcripts can be loaded by id or path
The transcript store SHALL load persisted RAG transcript JSON by transcript id or direct artifact path.

#### Scenario: Load by transcript id
- **WHEN** a transcript was previously stored for a transcript id
- **THEN** the transcript store SHALL load the matching persisted transcript envelope by that id

#### Scenario: Load by artifact path
- **WHEN** an operator provides a path to a persisted transcript JSON file
- **THEN** the transcript store SHALL load that transcript envelope without requiring an id lookup

### Requirement: Local replay command replays persisted transcripts
The local development command surface SHALL provide a deterministic RAG replay command for persisted transcripts.

#### Scenario: Replay persisted gated ask transcript
- **WHEN** an operator runs `python -m scripts.dev replay-rag <transcript-id-or-path>`
- **THEN** the command SHALL load the persisted transcript
- **AND** it SHALL run deterministic RAG replay without invoking retrieval, tools, memory, or LLM workers
- **AND** it SHALL print a JSON replay report
