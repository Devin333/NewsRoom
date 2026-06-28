## Why

The PRD calls for `framework/rag/generation/contracts.py` and `framework/rag/generation/grounding.py`. Research currently owns generic generated-answer shape and numbered-context prompt construction. The LLM call and paper context selection should stay in Research for now, but the output contract, grounded prompt builder, and citation index parsing are domain-neutral.

## What Changes

- Add `framework/rag/generation/contracts.py`.
- Add `framework/rag/generation/grounding.py`.
- Introduce `GeneratedRAGAnswer`, `RAGGenerationContext`, `build_numbered_context_prompt()`, and `cited_context_indexes()`.
- Rewire Research `AnswerGenerator` to use the kernel prompt builder and expose a kernel answer projection.
- Keep Paper-specific context selection, LLM call orchestration, benchmark wiring, and answer evaluation in Research.
- Add framework unit tests for generation contracts, prompt construction, and citation index parsing.

## Capabilities

### New Capabilities

- `rag-kernel-generation-contracts`: domain-neutral generated answer/context contracts and grounded numbered-context prompt utilities.

### Modified Capabilities

- `paper-rag-generation-prompt-migration`: Paper answer generation delegates generic prompt construction to the RAG kernel while preserving Paper-facing behavior.

## Impact

Affected code is limited to `framework/rag/generation`, `business/research/rag/generator.py`, tests, and this OpenSpec change. Existing Paper answer generation prompt text remains compatible.
