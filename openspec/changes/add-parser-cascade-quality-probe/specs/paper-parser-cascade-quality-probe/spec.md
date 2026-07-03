## ADDED Requirements

### Requirement: PDF parser cascade records every attempt
Paper PDF parsing SHALL support a cascade that tries configured parser backends in order and records every attempt in document metadata.

#### Scenario: First parser passes quality
- **WHEN** the first configured parser returns a document that passes the quality probe
- **THEN** the cascade returns that document
- **AND** document metadata identifies the used backend
- **AND** document metadata contains a successful attempt for that backend

### Requirement: Low-quality or failed parser attempts fall through
The parser cascade MUST fall through to the next backend when a parser raises an error or returns a document rejected by the deterministic quality probe.

#### Scenario: First parser is rejected by quality probe
- **WHEN** the first configured parser returns too little usable text
- **THEN** the cascade records a `quality_rejected` attempt
- **AND** tries the next configured parser

### Requirement: PyMuPDF text fallback is terminal and traceable
The parser cascade SHALL return a degraded PyMuPDF text document when every configured structured parser fails or is rejected.

#### Scenario: All structured parsers fail
- **WHEN** all configured parser backends fail or are rejected
- **THEN** the cascade returns a PyMuPDF fallback document
- **AND** the document metadata marks the result as degraded
- **AND** the parser cascade metadata records the fallback attempt

### Requirement: Chunk manifests include parser cascade trace
Chunk manifests SHALL include parser cascade trace metadata when chunks are produced from a cascaded parse.

#### Scenario: Chunk pipeline writes manifest after cascaded parse
- **WHEN** a parsed document contains parser cascade metadata
- **THEN** the chunk manifest includes the parser cascade summary
