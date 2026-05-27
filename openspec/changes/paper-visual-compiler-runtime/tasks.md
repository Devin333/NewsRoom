## 1. OpenSpec and Runtime Models

- [x] 1.1 Validate OpenSpec artifacts for `paper-visual-compiler-runtime`.
- [x] 1.2 Add Paper Visual Compiler domain models and local repository.

## 2. Backend Compiler Pipeline

- [x] 2.1 Implement PyMuPDF provider for page rendering, text blocks, visual crops, source bboxes, and manifests.
- [x] 2.2 Implement Asset Gate validation for file integrity, dimensions, blankness, captions, labels, source bboxes, and block bindings.
- [x] 2.3 Implement AI review interface, deterministic fallback behavior, compile orchestration, and publication status transitions.

## 3. Backend Integration

- [x] 3.1 Add `papers.visual_compile` worker handler and enqueue compile after paper ingest.
- [x] 3.2 Add backend document, compile-status, manual compile, asset, and source-preview API routes.

## 4. Frontend Reader Delivery

- [x] 4.1 Add shared paper-reader types and API client helpers.
- [x] 4.2 Add Next.js BFF routes for document, compile-status, compile, asset, and source-preview.
- [x] 4.3 Build `/papers/[slug]/read` formal reader with compiled-only body, outline, visual cards, AI panel, status blocking, and source preview.
- [x] 4.4 Update reader interaction target handling for paragraph, figure, table, and equation blocks.

## 5. Tests

- [x] 5.1 Add backend tests for compiler output, gate blocking, review behavior, repository status, worker, and API routes.
- [x] 5.2 Add frontend tests for compiled rendering, non-compiled blocking, AI-body isolation, visual cards, source preview, and interaction targets.

## 6. Verification

- [x] 6.1 Run OpenSpec strict validation.
- [x] 6.2 Run backend compile, test, and smoke checks.
- [x] 6.3 Run frontend paper tests, typecheck, and build.
- [x] 6.4 Commit the completed implementation.
