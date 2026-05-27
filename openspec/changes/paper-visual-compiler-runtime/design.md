## Context

Open Reader has a legacy reader payload built from extracted text, metadata, AI summaries, method signals, and experiment signals. That payload remains useful for Q&A and related-paper surfaces, but it is not a reliable article-body contract because AI-derived content can enter the same rendering flow as paper text.

The new runtime introduces a precompiled `PaperDocument` artifact. It is produced from the source PDF, validated by deterministic asset checks, reviewed by an AI reviewer, and then published as the only document that the formal reader renders. Runtime reads are intentionally passive: `GET document` never compiles on demand.

## Goals / Non-Goals

**Goals:**

- Compile source PDFs into structured blocks, visual assets, manifests, compile info, gate results, and review reports.
- Store compiled artifacts in local runtime storage first, without requiring a database migration.
- Block publication when deterministic Gate fails or AI review is unavailable/rejected.
- Expose status, document, asset, source-preview, and manual compile APIs.
- Queue compile work after paper ingest and through manual recompile using the same worker task.
- Render only `status === "compiled"` documents as the article body in `/papers/[slug]/read`.
- Keep AI summaries, method signals, experiment signals, and old reader sections outside the article-body stream.

**Non-Goals:**

- Perfect semantic reconstruction of tables or equations in the first version.
- Replacing the legacy reader payload used by Q&A, related papers, or existing compatibility paths.
- Introducing a new database schema for compiled paper storage.
- Running PDF compilation in the frontend request path.

## Decisions

1. Store Paper Visual Compiler artifacts under `.newsroom/papers/visual-compiler/{paper_id}/`.
   - Rationale: matches the repository's local JSON runtime pattern and keeps image assets near their manifest.
   - Alternative considered: database-backed binary storage. Deferred until publication lifecycle and retention requirements require it.

2. Use PyMuPDF as the default compiler provider behind a provider interface.
   - Rationale: the project already depends on PyMuPDF and it can render page images, text blocks, and crop rectangles without adding a new service.
   - Alternative considered: pdffigures2 or layout-model extraction. The provider boundary keeps those options pluggable later.

3. Treat Asset Gate as the publication authority before AI review.
   - Rationale: file existence, dimensions, checksums, blankness, labels, captions, and source bboxes are deterministic and must not be overridden by AI.
   - Alternative considered: letting AI decide final publication. Rejected because AI review cannot prove asset integrity.

4. Treat AI review as a required post-Gate quality signal for publication.
   - Rationale: the product requirement is that unreadable or mismatched visual documents stay out of the formal reader. If review is unavailable, the system records a review-blocked status instead of publishing.
   - Alternative considered: publish on Gate success with warnings. Rejected for the first formal reader because it can expose confusing article layouts.

5. Keep legacy reader sections as compatibility data only.
   - Rationale: Q&A, related papers, and existing reader tools can continue to use the old payload, while the new article surface has a clean source-of-truth contract.
   - Alternative considered: filtering the old sections at render time. Rejected because the source ambiguity remains.

## Risks / Trade-offs

- PyMuPDF heuristics can miss some figure/table/equation boundaries. Mitigation: preserve full page images, record warnings, expose source-preview bboxes, and keep the provider swappable.
- AI review availability can delay publication. Mitigation: status APIs expose the exact blocking reason and manual recompile uses the same queue path.
- Local file storage can grow with rendered page images. Mitigation: manifests make retention and cleanup discoverable; storage remains scoped per paper.
- Frontend and legacy reader paths may diverge. Mitigation: shared paper-reader types and tests assert the formal article body only consumes `PaperDocument.blocks`.

## Migration Plan

1. Add the compiler runtime and repository without changing existing reader APIs.
2. Add document/status/assets/source-preview API routes.
3. Queue compile tasks after successful paper ingest while retaining existing ingest behavior.
4. Add `/papers/[slug]/read` and route `/papers/[slug]` to it when appropriate.
5. Keep the old payload available for auxiliary features and compatibility.
6. Rollback can disable enqueue/manual compile and the new read route while leaving existing reader payloads untouched.

## Open Questions

- Which future visual provider should replace heuristics for complex academic layouts is intentionally left open behind the provider interface.
- Production retention policy for page images and crops will be handled after local artifact usage stabilizes.
