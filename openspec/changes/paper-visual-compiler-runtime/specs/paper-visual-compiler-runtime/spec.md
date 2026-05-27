## ADDED Requirements

### Requirement: PDF compilation produces PaperDocument artifacts
The system SHALL compile a paper source PDF into a versioned `PaperDocument`, `PaperAssetManifest`, `PaperCompileInfo`, and `PaperReviewReport` artifact set stored under a paper-specific visual compiler directory.

#### Scenario: Successful PDF compile creates document blocks and assets
- **WHEN** a paper with an available source PDF is compiled
- **THEN** the compiler stores page images, structured paragraph/heading/figure/table/equation blocks, visual assets with source bboxes, a manifest, compile info, and review metadata for that paper.

#### Scenario: Missing source PDF fails compile without publishing
- **WHEN** a paper compile is requested but no source PDF can be resolved
- **THEN** the compiler records a `compile_failed` status with diagnostics and no published document is returned.

### Requirement: Asset Gate controls publication
The system SHALL run a deterministic Asset Gate before publication and SHALL block publication on hard errors.

#### Scenario: Gate blocks missing or invalid assets
- **WHEN** a compiled document references a visual asset whose file is missing, has invalid dimensions, checksum mismatch, excessive blankness, missing label/caption, or missing source bbox
- **THEN** the Gate records hard errors and the paper status becomes `needs_review` or `compile_failed` instead of `compiled`.

#### Scenario: Gate accepts valid block asset bindings
- **WHEN** every visual block references an existing manifest asset with valid metadata and matching source information
- **THEN** the Gate allows the AI review stage to run.

### Requirement: AI review is required after Gate success
The system SHALL run an AI review after deterministic Gate success and SHALL publish only when the review verdict passes.

#### Scenario: AI review passes compiled document
- **WHEN** Asset Gate passes and the AI reviewer returns an approval verdict
- **THEN** the repository publishes the document with status `compiled` and stores the review report.

#### Scenario: AI review unavailable blocks publication
- **WHEN** Asset Gate passes but the AI reviewer is unavailable or returns a non-approval verdict
- **THEN** the repository stores review diagnostics and does not publish the document.

### Requirement: Compilation runs in background tasks
The system SHALL compile papers through worker task `papers.visual_compile` for both ingest-triggered and manual compile requests.

#### Scenario: Ingest enqueues visual compile
- **WHEN** a paper ingest completes with a resolvable PDF source
- **THEN** the system enqueues `papers.visual_compile` without blocking the ingest response on compilation.

#### Scenario: Document read does not trigger compile
- **WHEN** a client requests a paper document
- **THEN** the API reads the latest published artifact/status and does not enqueue or execute compilation.

### Requirement: Paper document APIs expose compiled artifacts safely
The system SHALL expose APIs for published document reads, compile status, manual compile enqueue, visual assets, and source previews.

#### Scenario: Published document returned
- **WHEN** a client requests `/api/v1/papers/{paper_id}/document` for a compiled paper
- **THEN** the API returns the compiled `PaperDocument` and auxiliary AI metadata outside the body stream.

#### Scenario: Unpublished document blocked
- **WHEN** a client requests a document for a paper whose status is not `compiled`
- **THEN** the API returns status and diagnostics without article-body blocks.

#### Scenario: Asset and source preview resolve from manifest
- **WHEN** a client requests an asset or source preview for a compiled paper
- **THEN** the API serves only files and crop previews referenced by the paper's manifest/source coordinates.
