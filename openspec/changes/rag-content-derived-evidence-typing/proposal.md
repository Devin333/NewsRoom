## Why

The current Harness RAG adapter assigns every returned evidence candidate the `evidence_type` requested by the planner, so coverage gates can pass even when the retrieved content is unrelated to the required type. This change makes evidence coverage measure retrieved content metadata instead of the request label.

## What Changes

- Add a framework-level evidence type resolver contract that can derive an evidence type from retrieved `RAGEvidence.metadata`.
- Update `KernelRAGRetrieverHarnessAdapter` to use a resolver per evidence item and record whether the label was content-resolved or fell back to the requested/default type.
- Add a Research-owned mapping from Paper chunk metadata (`section_role`, `chunk_type`) to Harness evidence types.
- Wire `PaperChunkRetrievalPort` through the content-derived resolver while preserving existing retrieval output shape and metadata.
- Add tests that lock Paper chunk metadata projection and prevent request labels from masking actual evidence content.

## Capabilities

### New Capabilities

### Modified Capabilities
- `rag-harness-kernel-retriever-adapter`: Harness kernel retrieval adapter derives candidate evidence types from retrieved evidence metadata when a resolver is configured.
- `paper-rag-kernel-adapter`: Paper RAG retrieval preserves structural chunk metadata required for Research-owned evidence type mapping.

## Impact

- Affected framework modules: `framework/harness/rag/kernel_evidence_adapter.py`, new `framework/harness/rag/evidence_typing.py`, `framework/harness/rag/__init__.py`.
- Affected Research modules: new `business/research/rag/evidence_typing.py`, `business/research/rag/retrieval_port.py`, Paper adapter tests.
- No new external dependencies.
- Existing callers that do not configure a resolver keep the previous requested/default evidence type behavior, with explicit source metadata for observability.
