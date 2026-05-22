## 1. OpenSpec

- [x] 1.1 Validate the OpenSpec change artifacts for `intelligence-memory-phase2-finalization`.

## 2. Reindex Observability

- [x] 2.1 Extend `MemoryReindexResult.to_dict()` with `counts`, `metadata`, and full `ingestion` payload while preserving legacy fields.
- [x] 2.2 Add reindex/API/MCP observability assertions for the enriched payload.

## 3. Recall Consumption

- [x] 3.1 Add `ReportMemoryContextService` request/result API and tests.
- [x] 3.2 Refactor daily `ReportWriter` to use the report memory context service while preserving `recall_service` compatibility.

## 4. Quality and Ranking

- [x] 4.1 Replace the daily quality gate's ad hoc memory conflict helper with `QualityMemoryChecker`-backed context checks.
- [x] 4.2 Add focused structured memory ranking integration coverage.

## 5. Pipeline and Repository Coverage

- [x] 5.1 Expand Phase 2 ingestion pipeline tests for duplicate claim merge, contradiction history, duplicate event skip, metadata, and structured vector collections.
- [x] 5.2 Add memory service factory tests for sinkless protection and structured vector adapter wiring.
- [x] 5.3 Expand Postgres timeline repository tests for event relations, claims, evidence, decisions, preferences, and claim history/status behavior.

## 6. Acceptance

- [x] 6.1 Run OpenSpec validation and targeted pytest acceptance commands.
