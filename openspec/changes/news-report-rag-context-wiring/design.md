# Design

## Scope

This change wires topic-level retrieved context into the existing board/report output path. It does not replace source collection, evidence building, or the paper-specific chunk RAG stack.

## Approach

`BoardOutputPipeline` accepts a narrow provider with `build_context(request)`. The request is a local duck-typed dataclass with `topic`, `run_id`, `entity_ids`, and `limit`, which remains compatible with `ReportMemoryContextService` without forcing the output layer to own memory storage details.

When a provider is configured:

1. The pipeline resolves the topic from `AnalysisContext.metadata["report_topic" | "topic" | "memory_topic"]`, then `RunContext.options`, then the board type label.
2. The provider returns a dict-like or `to_dict()` payload.
3. `ReportBuilder` stores the payload under `report.metadata["rag_context"]`.
4. If the payload includes non-empty `prompt_context`, the builder appends a `Retrieved Context` evidence section.

If the provider raises, the pipeline records a diagnostic unavailable context and still returns the report. This keeps report generation robust when memory search is temporarily unavailable.

## Boundaries

- The output layer does not import storage or concrete vector clients.
- The provider is optional, so existing tests and smoke paths keep their default behavior.
- Retrieved context is contextual input/evidence. It does not decide routing, quality pass/fail, memory writes, or publication.
