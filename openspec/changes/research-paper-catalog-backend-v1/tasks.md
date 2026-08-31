## 1. Contract And Domain

- [x] 1.1 Add PRD, proposal, design, spec and task artifacts for the Research Paper Catalog change.
- [x] 1.2 Add source types, parse/catalog statuses, source snapshots, paper identity and conflict diagnostics.
- [x] 1.3 Add typed catalog entries/relations and repository/query ports with actor-scope fields.

## 2. Parse Application Path

- [x] 2.1 Implement source resolver adapters and checksum/canonical identity idempotency.
- [x] 2.2 Implement `ParsePaperRequest`, `ParsePaperResult` and bounded `ParsePaperUseCase`.
- [x] 2.3 Persist documents, parser attempts, quality reports, chunk manifests, evidence packs and artifact refs.
- [x] 2.4 Emit durable phase, retry, degrade, conflict and failure events.

## 3. Catalog And Trust Gates

- [x] 3.1 Implement filesystem Catalog/source/document repositories and relation upsert semantics.
- [x] 3.2 Add GitHub README/install/examples/training/inference/checkpoint observations.
- [x] 3.3 Add deterministic score compatibility and candidate/verified/conflicting leaderboard gates.
- [x] 3.4 Add Catalog query, search, refresh and projection services.

## 4. Interfaces

- [x] 4.1 Extend the research application facade with parse, source, document, catalog, code and benchmark operations.
- [x] 4.2 Add the v1 HTTP routes and shared JSON response/error/provenance contract.
- [x] 4.3 Add `paper` CLI parse/ingest/refresh/catalog/benchmark/code commands with `--json`.

## 5. Verification

- [x] 5.1 Add unit and integration tests for identity merge, metadata-only denial, parser fallback, idempotency, actor isolation and trust gates.
- [x] 5.2 Verify API/CLI call only application services and that `frontend` and legacy `paper_radar` remain untouched.
- [x] 5.3 Run compile, tests, smoke and strict OpenSpec validation; commit the completed change.
