## Context

The PDF pipeline currently parses figure/table captions, crops Surya regions, writes image references, and emits figure/table `PaperChunk` objects. Figure chunks are also eligible for CLIP visual indexing. The ambiguous part is contextual binding: a nearby paragraph is useful for retrieval text, but it is not proof that the visual element is located near that paragraph, and body references can appear before or after the figure/table.

## Goals / Non-Goals

**Goals:**
- Represent visual region evidence, caption evidence, and body-reference evidence separately in chunk metadata.
- Preserve current chunk types and storage schema.
- Make figure/table chunks explainable through match strategy, confidence, page, bbox, and referring paragraph ids.
- Keep retrieval text useful by including caption and referenced paragraph snippets without confusing them with source location.

**Non-Goals:**
- Replacing Surya/Nougat/PyMuPDF extraction.
- Adding column-level table chunking.
- Building a UI for alignment review.
- Changing Qdrant/Postgres schemas beyond payload metadata.

## Decisions

- Use `PaperChunk.metadata` for new alignment fields instead of adding new top-level model fields. This preserves existing storage contracts and avoids migrations.
- Keep one parent figure/table chunk per visual element. Long tables continue to emit row-group child chunks; caption remains part of the parent table chunk.
- Detect body references from paragraph chunks with deterministic regexes for `Figure/Fig.` and `Table` labels, then attach `referenced_by_chunks` to matching figure/table chunks.
- Keep `parent_chunk_id` as structural proximity/context and add `referenced_by_chunks` for explicit body references. These are different relationships.
- Record match provenance using explicit fields such as `caption_match_strategy`, `caption_match_confidence`, `visual_region`, `caption_region`, and `nearby_context_chunk_id`.

## Risks / Trade-offs

- Regex reference detection can miss unusual wording or ranges → Store it as best-effort metadata and never use it to overwrite visual locators.
- Existing metadata is heterogeneous between PDF and LaTeX parsers → Helper functions normalize known keys and gracefully omit missing fields.
- Additional metadata increases payload size → Keep snippets bounded and store ids/locators rather than full paragraph bodies.

## Migration Plan

Existing chunks remain readable. New ingests or re-ingests will include the enhanced metadata. Rollback is limited to reverting the chunker metadata helpers because no storage schema migration is introduced.
