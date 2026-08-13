## ADDED Requirements

### Requirement: Paper ingest uses agent analysis by default
Paper ingest SHALL run `PaperAnalysisOrchestrator` as the official default classification/profile path.

#### Scenario: Default ingest invokes paper agent analysis
- **WHEN** paper ingest classifies a candidate
- **THEN** it calls the paper analysis orchestrator without requiring a feature flag

### Requirement: Paper ingest uses durable session storage by default
The default paper analysis orchestrator created by ingest SHALL use `SQLiteAgentSessionStore`, not in-memory storage.

#### Scenario: Default store path is available
- **WHEN** no session store path is configured
- **THEN** ingest uses a local `.newsroom/paper-agent-sessions.sqlite3` SQLite path

### Requirement: Legacy classifier is fallback-only and marked
The legacy LLM classifier SHALL only run when agent analysis fails or produces no publishable task/method refs and fallback is enabled.

#### Scenario: Agent failure falls back to legacy classifier
- **WHEN** agent analysis fails and legacy fallback is enabled
- **THEN** ingest runs the legacy classifier, records prompt memory, and marks classification with legacy fallback metadata and warnings

#### Scenario: Legacy fallback can be disabled
- **WHEN** agent analysis fails and legacy fallback is disabled
- **THEN** ingest raises a classification error instead of silently using the legacy classifier

### Requirement: Final profile fields are preserved in PublicPaper payloads
The ingest payload SHALL preserve final profile task refs, method refs, benchmarks, classification metadata, AI summary, and evidence summary.

#### Scenario: Published paper contains agent profile fields
- **WHEN** agent analysis returns a final profile
- **THEN** the published paper contains compatible task refs, method refs, benchmarks, classification, and summary fields

### Requirement: Old reader, citation, and backfill flows remain compatible
Existing reader, citation, and classification backfill behavior SHALL continue to work while using the final agent path or marked legacy fallback.

#### Scenario: Backfill can use legacy fallback
- **WHEN** backfill's agent analysis path fails
- **THEN** backfill can use the legacy classifier fallback and preserve existing repair handling
