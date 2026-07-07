# Design

## Service Behavior

`PaperRagApplicationService.rag_ask(generate=True)` always routes to `_gated_ask()` when `gated=True`.

If a direct caller passes `generate=True, gated=False`, the service raises `ValueError` before retrieval or generation. This keeps old callers from silently getting an ungated answer.

Retrieve-only calls (`generate=False`) continue to use the retriever path and tenant payload filtering.

## CLI Behavior

`paper ask --answer` always uses gated Harness answer generation. The `--legacy-direct-answer` flag is removed from the parser.

## Removed Dependency

The service no longer imports or instantiates the old direct `AnswerGenerator` path.
