## ADDED Requirements

### Requirement: Formal reader renders only compiled documents
The frontend SHALL render the formal `/papers/[slug]/read` article body only from a backend `PaperDocument` whose status is `compiled`.

#### Scenario: Compiled paper body renders
- **WHEN** the reader receives a `compiled` document with paragraph, heading, figure, table, and equation blocks
- **THEN** it renders the article body from those blocks and uses manifest assets for visual cards.

#### Scenario: Non-compiled paper blocks body rendering
- **WHEN** the reader receives `queued`, `compiling`, `needs_review`, `compile_failed`, `review_failed`, or missing document status
- **THEN** it shows compile status and diagnostics but does not render legacy sections as a substitute article body.

### Requirement: AI content is isolated from paper body
The frontend SHALL keep AI summaries, method signals, experiment signals, recommendations, and review diagnostics outside the article-body block flow.

#### Scenario: AI summary stays out of body
- **WHEN** a compiled document includes auxiliary AI metadata
- **THEN** the article body renders only `PaperBlock` content and the AI metadata appears only in dedicated panel or auxiliary regions.

### Requirement: Reader interactions target compiled block types
The frontend SHALL emit reader interaction targets that identify paragraph, figure, table, and equation blocks with optional asset and source bbox metadata.

#### Scenario: Figure interaction includes asset source
- **WHEN** a reader opens a figure explanation, note, or source preview
- **THEN** the event target includes the block id, target type `figure`, asset id, page number, and source bbox when available.

#### Scenario: Paragraph interaction identifies paper block
- **WHEN** a reader selects or annotates a paragraph
- **THEN** the event target includes the paragraph block id and does not depend on legacy section identifiers.

### Requirement: Next BFF mirrors paper document APIs
The Next.js BFF SHALL expose `/api/papers/...` routes that mirror backend document, compile-status, compile, assets, and source-preview endpoints.

#### Scenario: BFF document route mirrors backend response
- **WHEN** the frontend requests `/api/papers/{slug}/document`
- **THEN** the BFF returns the backend document/status payload without compiling on demand.

#### Scenario: BFF asset route streams visual asset
- **WHEN** the frontend requests a visual asset route
- **THEN** the BFF streams the backend asset response with the correct content type.
