## Context

`DeterministicRAGPlanner` records the evidence type it wants in retrieval step metadata. `KernelRAGRetrieverHarnessAdapter` currently copies that requested type onto every returned candidate. The session coverage gate then compares accepted candidate `evidence_type` values against required types, which makes coverage a reflection of planner intent rather than actual retrieved content.

Paper chunks already carry useful structural signals. `PaperChunkAdapter` projects `chunk_type` and `section_role` into `RAGEvidence.metadata`, and Research can map those domain values to Harness-level evidence types without teaching framework code about papers.

## Goals / Non-Goals

**Goals:**
- Keep framework code domain-neutral.
- Allow each evidence candidate to receive an evidence type from its own metadata.
- Preserve backward compatibility when no resolver is configured.
- Expose `evidence_type_source` in candidate metadata so reports can distinguish content-resolved evidence from fallback labels.
- Wire Paper RAG retrieval to use Research-owned metadata mapping.

**Non-Goals:**
- Add relevance scoring, reranking, or LLM planning.
- Change `required_evidence_types` policy construction.
- Change Paper retrieval ranking, benchmark generation, or parser output.
- Remove the request/default fallback behavior.

## Decisions

1. Add `EvidenceTypeResolver` to `framework/harness/rag/evidence_typing.py`.

   The resolver is a small protocol with `resolve(metadata) -> str | None`. Returning `None` means the adapter must fall back to request/default evidence type. This keeps the framework open to multiple domains without importing Research code.

2. Implement `MetadataKeyEvidenceTypeResolver` as a declarative mapping resolver.

   The resolver checks mapping keys in declaration order and supports scalar or list metadata values. Research can prioritize `section_role` before `chunk_type`, so a paragraph in a method section maps to `method`, while standalone table/figure/formula chunks can still map by `chunk_type` when no role signal exists.

3. Record evidence type provenance in candidate metadata.

   `content_resolved` means resolver found a content signal. `requested_fallback` means a resolver was configured but could not resolve the item. `requested_default` means no resolver was configured and the adapter used existing request/default behavior.

4. Keep Paper-specific mapping in `business/research/rag/evidence_typing.py`.

   Mapping `section_role` and `chunk_type` is a Research concern. Framework only knows that metadata can be resolved; it does not know what `method`, `experiment`, `formula`, or `table` mean for papers.

## Risks / Trade-offs

- Some sessions that previously passed coverage may become insufficient after content-derived typing exposes the real evidence mix. This is intended and should be treated as surfacing truth rather than a retrieval regression.
- `section_role` can be imperfect when parser output is weak. The request/default fallback remains available and is explicitly marked for analysis.
- A simple mapping table is less expressive than a learned classifier, but it is deterministic, explainable, and appropriate for this T1 slice.
