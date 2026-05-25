## Why

Paper Reader needs to move from a preview/list experience to a reliable reader surface. The current browser client can still call `/api/v1/papers` directly, backend data defaults still depend on frontend files, and PaperRadar artifacts are not yet a first-class source for public paper DTOs.

## What Changes

- Add a Next.js BFF for paper list/detail/summary calls so browser requests use `/api/papers...` and server-side code carries backend tokens.
- Preserve backend paper DTO fields in frontend data loading instead of re-normalizing authoritative API responses through fallback cache parsing.
- Change backend paper data source priority to latest valid PaperRadar artifact, then `.newsroom/papers` cache, while retaining frontend local fallback for UI resilience.
- Add an initial `/papers/[slug]` reader page with paper metadata, PDF/text fallback, AI reader panel, and related entity placeholders.
- Add PaperRadar artifact repository, public mapper, and reader payload builder boundaries with public DTO redaction and non-paper filtering.

## Capabilities

### New Capabilities
- `paper-reader-runtime`: Browser-safe Paper Reader API access, authoritative paper DTO preservation, reader payloads, and PaperRadar artifact-backed public paper data.

### Modified Capabilities

## Impact

- Backend services: `PapersApplicationService`, new PaperRadar artifact repository/mapper/reader builder, and related tests.
- Frontend: paper API client, SSR paper loading, Next.js BFF routes, paper types, drawer link, reader page, and tests.
- Runtime/config: backend default paper cache path changes from `frontend/data/papers` to `.newsroom/papers`.
