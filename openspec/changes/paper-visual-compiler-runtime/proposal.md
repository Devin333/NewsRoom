## Why

Open Reader currently can mix extracted paper text with AI summaries and derived signals, which makes the article body ambiguous and can show generated content where the reader expects the paper itself. Paper reading needs a precompiled, gate-reviewed document artifact so readers see the real paper body immediately while AI output remains clearly separated.

## What Changes

- Add a Paper Visual Compiler runtime that turns source PDFs into structured `PaperDocument` blocks, real page/figure/table image assets, and generated equation text blocks stored under `.newsroom/papers/visual-compiler/{paper_id}/`.
- Add deterministic Asset Gate validation for referenced figure/table assets, image dimensions, checksums, blankness, captions/labels, source bboxes, block-to-asset bindings, and equation text/source coordinates.
- Add an AI review stage after deterministic Gate success; documents are not published when review is unavailable or rejects the compiled result.
- Add background and manual compile surfaces through worker task `papers.visual_compile`; document reads never trigger compilation.
- Add Paper Document APIs for published documents, compile status, manual compile enqueue, visual assets, and source previews.
- Add a formal `/papers/[slug]/read` frontend reader that renders only compiled paper blocks as the article body, keeps AI summaries/signals in auxiliary panels, and blocks pseudo-body rendering for non-compiled documents.
- Preserve older reader payload compatibility for Q&A, related papers, and auxiliary reader data while removing `sections[]` from the new article-body path.

## Capabilities

### New Capabilities
- `paper-visual-compiler-runtime`: Compiles source PDFs into gated, AI-reviewed PaperDocument artifacts and exposes their status, assets, and source previews.
- `paper-document-reader-delivery`: Delivers the compiled PaperDocument to the frontend reader and renders only published paper-body blocks while isolating AI summaries and signals.

### Modified Capabilities
- None.

## Impact

- Affects paper radar business modules, paper ingest and worker handlers, paper API routes, local runtime storage, Next.js BFF routes, and Open Reader frontend components.
- Uses the existing PyMuPDF dependency for PDF rendering and visual crop extraction.
- Adds tests for compiler output, Asset Gate blocking, AI review decisions, worker idempotency, document APIs, frontend compiled rendering, status blocking, source previews, and interaction target typing.
