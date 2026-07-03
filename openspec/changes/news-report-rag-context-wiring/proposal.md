# News Report RAG Context Wiring

## Why

The enterprise RAG review lists "news main path RAG integration" as a remaining P2 gap. NewsRoom already indexes prior reports and evidence into memory, and `ReportMemoryContextService` can build prompt-safe historical context for a topic, but the board/report output pipeline does not consume that context when constructing the main news report payload.

## What Changes

- Allow `BoardOutputPipeline` to accept an optional report context provider.
- Resolve a report topic from `AnalysisContext` metadata/run options or the board type.
- Build report retrieval context through the injected provider before `ReportBuilder` constructs the report.
- Project retrieved context into report metadata and add a `Retrieved Context` evidence section when prompt context is non-empty.
- Degrade safely when the context provider is absent or fails.

## Capabilities

### New Capabilities

- `news-report-rag-context-wiring`: report output can carry retrieved memory/RAG context on the main news path.

### Modified Capabilities

None.

## Impact

Affected code is limited to `business.layers.output` and focused output tests. No storage migration, source ingestion change, or paper-specific RAG dependency is introduced.
