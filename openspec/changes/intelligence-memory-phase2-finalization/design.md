## Context

Phase 1 and Phase 2 established the structured memory model, Postgres repository, Phase 2 ingestion pipeline, Recall v2, and structured vector indexing. The remaining work is not a new memory model; it is closing the business feedback loop so run/reindex outputs are observable and writer, ranking, and quality paths consume memory in a deterministic, additive way.

## Goals / Non-Goals

**Goals:**
- Expose structured ingestion counts and metadata through reindex results and existing API/MCP/CLI surfaces.
- Normalize report writer recall consumption through a small report memory context service.
- Use `QualityMemoryChecker` for daily memory quality metadata and critical blocking decisions.
- Keep `MemoryFeatureComputer` ranking consumption explicit and covered by tests.
- Expand repository and pipeline tests around merge, contradiction, event duplicate, history, timeline, and relation behavior.

**Non-Goals:**
- No new graph database, LLM extraction, runner path, background consolidation worker, or framework memory runtime replacement.
- No redesign of production ranking weights or the daily quality gate beyond additive memory checks.
- No change to Postgres as structured source of truth or vector storage as semantic index only.

## Decisions

- Reindex result enrichment happens in `MemoryReindexResult.to_dict()` so existing API, MCP, and CLI callers inherit the new observability without duplicating payload assembly.
- Report writing uses a new `ReportMemoryContextService`, but `ReportWriter(recall_service=...)` remains valid by wrapping the recall service internally.
- Daily quality converts serialized `memory_context` back into `IntelligenceMemoryContext` and runs `QualityMemoryChecker` with a safe empty query repository. Critical issues can block; high/medium issues are recorded without replacing existing citation/support logic.
- Ranking remains opt-in through `BusinessMemoryDecisionService` injection. Tests assert structured features only appear when an intelligence repository or feature computer is configured.

## Risks / Trade-offs

- Serialized memory context may omit fields needed to reconstruct full memory dataclasses -> use permissive coercion helpers that ignore unknown fields and default missing optional values.
- `QualityMemoryChecker` expects repository methods for some checks -> use a minimal no-op query repository for context-only checks and rely on embedded claim/event data when available.
- More observable payloads may affect exact dict assertions -> update tests to assert compatibility fields plus new structured fields instead of exact legacy payloads.
