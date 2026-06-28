# rag-kernel-source-span Specification

## Purpose
TBD - created by archiving change rag-kernel-source-span-migration. Update Purpose after archive.
## Requirements
### Requirement: Kernel builds main and overlap span metadata
The RAG kernel SHALL provide a domain-neutral metadata builder for main content spans and overlap-origin spans.

#### Scenario: Paragraph has overlap text
- **WHEN** overlap text is present
- **THEN** metadata includes `content_span_unit`, `main_span`, and `overlap_spans`
- **AND** the overlap span records origin chunk and origin source locator

### Requirement: Kernel resolves source spans
The RAG kernel SHALL resolve whether a cited snippet belongs to the current main span or an overlap span.

#### Scenario: Snippet lands in overlap
- **WHEN** the resolved snippet span falls inside an overlap span
- **THEN** the resolver returns the overlap origin chunk and source locator

#### Scenario: Snippet lands in main content
- **WHEN** the resolved snippet span falls outside overlap spans
- **THEN** the resolver returns the current chunk and source locator

### Requirement: Paper citation spans use kernel span logic
Research document citation span helpers SHALL delegate generic span logic to the RAG kernel while keeping PaperChunk-facing APIs in Research.

#### Scenario: Paper wrapper shape is preserved
- **WHEN** Research calls `build_paragraph_span_metadata()` or `resolve_citation_span()`
- **THEN** the returned dictionary shape remains compatible with existing Paper tests and evidence metadata

