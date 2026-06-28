## ADDED Requirements

### Requirement: Context pack exposes evidence artifact refs
The Harness RAG context pack SHALL expose artifact refs associated with accepted, rejected, or conflicting evidence.

#### Scenario: Evidence artifact refs are serialized
- **WHEN** a context pack is assembled from evidence candidates with artifact refs
- **THEN** the context pack serialization includes pack-level artifact refs
- **AND** each evidence candidate serialization includes its own artifact refs

### Requirement: Context pack exposes evidence trace rows
The Harness RAG context pack SHALL expose trace rows for accepted, rejected, and conflicting evidence.

#### Scenario: Trace rows preserve source and span refs
- **WHEN** a context pack is assembled
- **THEN** each trace row includes status, evidence id, evidence type, source ref, span refs, artifact refs, lineage, confidence, and score breakdown

### Requirement: Context envelope preserves trace metadata
The Harness context envelope produced from a RAG context pack SHALL preserve evidence trace metadata.

#### Scenario: Context envelope includes traceability metadata
- **WHEN** a RAG context pack is converted into a context envelope
- **THEN** the envelope artifact refs match the pack artifact refs
- **AND** envelope metadata includes the evidence trace
