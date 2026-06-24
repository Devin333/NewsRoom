## Context

`PaperDocumentChunker` already emits standalone formula chunks and picks one primary parent paragraph using LaTeX text matching, page locator matching, or fallback. Paragraph chunks also record inline/display formula text with `has_formula` and `formula_latex`. The missing piece is explicit reference edges from body paragraphs to known formulas.

## Goals / Non-Goals

**Goals:**
- Keep one primary `parent_chunk_id` per formula chunk.
- Record all deterministic paragraph references to known equations in formula chunk metadata.
- Make formula location and parent match strategy replayable and separate from later references.

**Non-Goals:**
- Full symbolic equation equivalence.
- LLM-based equation reference resolution.
- Changing storage schemas or chunk types.
- Emitting per-reference formula chunks.

## Decisions

- Store new fields in `PaperChunk.metadata` to avoid persistence migrations.
- Build equation lookup keys from `equation_id`, `equation_number`, `equation_label`, and common normalized ids.
- Detect references before paragraph overlap augmentation so injected context does not create false positives.
- Attach reference edges after paragraph chunks are created, mirroring the visual element reference pattern.

## Risks / Trade-offs

- Regex matching can miss unusual references or equation ranges -> keep this deterministic V1 narrow and explicit.
- Equations without numbers or labels may not receive references -> they still keep the existing primary parent binding.
- Repeated references in the same paragraph can create noisy duplicates -> dedupe by chunk id and text reference.

## Migration Plan

Existing chunks remain valid. New ingests or re-chunking will include `formula_references` and formula `referenced_by_chunks`. Rollback only removes metadata enrichment; no schema rollback is needed.
