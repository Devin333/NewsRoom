## ADDED Requirements

### Requirement: Kernel collects nearby context ids
The RAG kernel SHALL collect related context ids from caller-provided metadata edge keys, parent ids, and reference-list metadata.

#### Scenario: Direct and referenced edges are deduplicated
- **WHEN** metadata contains direct context ids and referenced-by chunk ids
- **THEN** the collector returns a deduplicated ordered id list
- **AND** exposes ids grouped by edge key

#### Scenario: Caller can choose edge keys
- **WHEN** a caller provides custom direct or reference-list keys
- **THEN** the collector reads only those requested keys

### Requirement: Paper answer context uses kernel nearby-id collection
Research answer context selection SHALL use the kernel helper for generic related-id extraction while preserving Paper-specific chunk selection behavior.

#### Scenario: Answer context ordering is preserved
- **WHEN** a retrieved figure or table points to nearby or referenced context
- **THEN** Paper answer context selection still interleaves the related chunk before unrelated leftover candidates
