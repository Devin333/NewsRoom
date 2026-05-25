## Context

Paper Reader already has a public FastAPI papers service and a frontend `/papers` stream, but browser requests can still target FastAPI directly and the server-side fallback path re-cleans backend data. The PRD requires the browser path to be `Browser -> Next.js BFF -> FastAPI`, backend data to stop defaulting to frontend files, and PaperRadar runtime artifacts to become the preferred data source.

## Goals / Non-Goals

**Goals:**
- Route browser paper list/detail/summary traffic through Next.js BFF endpoints.
- Preserve authoritative `PublicPaper` fields returned by the backend.
- Prefer valid PaperRadar paper artifacts over static cache data.
- Provide an initial full reader page with PDF/text fallback and AI summary context.

**Non-Goals:**
- No Reader Agent or live Ask-this-paper Q&A.
- No user collections, subscriptions, reading state, or private PDF upload.
- No full PDF text extraction pipeline.

## Decisions

- Use Next.js route handlers for BFF endpoints. This keeps backend tokens on the server and reuses the existing server API client that already reads `NEWSROOM_API_TOKEN` / `NEWS_API_TOKEN`.
- Keep FastAPI `/api/v1/papers` as the authoritative backend contract. The BFF only forwards and normalizes transport errors.
- Add a small PaperRadar artifact repository that reads local run manifests and known artifact names. This avoids coupling `PapersApplicationService` to workflow internals while still making artifact priority explicit.
- Map only true paper signals/cards to `PublicPaper`. Known news/blog/source types are filtered, and raw/private fields are recursively redacted before public DTO creation.
- Build reader payloads from existing metadata and cached summaries. Sections are lightweight v1 placeholders derived from abstract/summary until full text extraction exists.

## Risks / Trade-offs

- PaperRadar artifacts may have inconsistent shapes -> mapper accepts multiple known shapes and falls back cleanly to cache.
- Local `.newsroom` is ignored and may be absent -> service continues to support env-injected temp paths and cache fallback.
- Reader page PDF rendering may fail for external sources -> page displays metadata and text fallback without blocking summary/reader context.
- BFF route handlers duplicate some forwarding logic -> keep them thin and tested through the paper client contract.
