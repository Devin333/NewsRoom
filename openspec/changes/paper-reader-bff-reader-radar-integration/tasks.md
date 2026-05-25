## 1. OpenSpec and Backend Runtime

- [x] 1.1 Create OpenSpec proposal, design, spec, and task artifacts.
- [x] 1.2 Add PaperRadar artifact repository for latest local run payload discovery.
- [x] 1.3 Add PaperRadar public mapper with true-paper filtering and recursive redaction.
- [x] 1.4 Add reader payload builder and service method.
- [x] 1.5 Change PapersApplicationService source priority and default cache path.

## 2. Frontend BFF and Data Flow

- [x] 2.1 Add Next.js BFF list/detail/summary routes.
- [x] 2.2 Update paper API client to use `/api/papers`.
- [x] 2.3 Update SSR paper loading to preserve authoritative backend fields.
- [x] 2.4 Extend paper frontend types for reader payload and evidence/source refs.

## 3. Reader Experience

- [x] 3.1 Add `/papers/[slug]` reader route and page components.
- [x] 3.2 Add drawer link to open the full reader page.
- [x] 3.3 Render PDF/text fallback, AI reader panel, implementation/benchmark sections, and related placeholders.

## 4. Tests and Validation

- [x] 4.1 Add backend service tests for path, redaction, mapper filtering, field preservation, and reader payload.
- [x] 4.2 Add frontend tests for BFF paths, field preservation, drawer reader link, and reader fallback.
- [x] 4.3 Run OpenSpec validation, backend papers tests, frontend papers tests, typecheck, and targeted e2e if navigation changed.
