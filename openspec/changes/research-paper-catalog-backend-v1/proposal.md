## Why

Research currently has capable parser, evidence, RAG and analysis building blocks, but no single application contract for ingesting a paper from heterogeneous sources into a durable, provenance-aware Paper-with-Code catalog. Callers can therefore bypass application boundaries, source conflicts are hard to inspect, and benchmark candidates can be confused with verified results.

## What Changes

- Add a multi-source paper identity and source snapshot aggregate with explicit conflict and access diagnostics.
- Add `ParsePaperRequest`, `ParsePaperResult` and a bounded synchronous `ParsePaperUseCase` that reuses existing parser cascade and artifact/chunk contracts.
- Add typed Catalog entries and relations, deterministic benchmark verification/leaderboard filtering, and GitHub reproducibility observations.
- Add durable filesystem repositories, application facade methods, HTTP routes, JSON contracts and `paper` CLI commands.
- Preserve the existing frontend and legacy parser/RAG implementations while making the new path depend only on research domain/application/ports.

## Capabilities

### New Capabilities

- `research-paper-catalog-backend-v1`: Traceable multi-source paper parsing and typed Paper-with-Code catalog lifecycle.

### Modified Capabilities

- None.

## Impact

Affected areas are `backend/research/domain`, `backend/research/application`, `backend/research/ports`, `infrastructure/research`, `interfaces/services`, `interfaces/api/routers/research.py`, and `interfaces/cli/commands/paper.py`, plus focused tests and OpenSpec artifacts. `frontend` is intentionally untouched.
