## ADDED Requirements

### Requirement: Kernel provides keyed first-seen deduplication
The RAG kernel SHALL provide a domain-neutral helper that deduplicates arbitrary values by caller-provided keys while preserving the first occurrence order.

#### Scenario: Duplicate keys preserve first item
- **WHEN** a sequence contains multiple items with the same dedupe key
- **THEN** the helper returns the first item for that key
- **AND** later duplicates are skipped
- **AND** the relative order of first occurrences is preserved

### Requirement: Evidence dedup behavior remains unchanged
Existing evidence deduplication SHALL continue to keep the highest scoring evidence for each evidence key.

#### Scenario: Higher-scoring duplicate wins
- **WHEN** `dedupe_evidence()` receives multiple evidence values for the same key
- **THEN** it keeps the highest scoring value
- **AND** the existing public behavior remains compatible

### Requirement: Paper chunk dedup uses kernel primitive
Research retrieval and evidence evaluation SHALL use kernel keyed deduplication for duplicate Paper chunks without moving Paper models into framework code.

#### Scenario: Paper chunks are deduped by chunk id
- **WHEN** Research retrieval or evidence evaluation deduplicates `PaperChunk` values
- **THEN** it calls the kernel keyed dedup helper with `chunk_id` as the key
- **AND** Paper-specific expansion, scoring, and ranking behavior remain unchanged
