## Context

The Research board loads papers through Next.js BFF routes and can fall back from backend data to tracked cache or latest artifacts. Task and method taxonomy currently has multiple sources: backend taxonomy, local static catalog, cache conversion, artifact conversion, and client-side fallback derivation. The user-visible result can overstate coverage because fallback papers are classified by title, abstract, or tags even when no real `taskRefs` or `methodRefs` exist.

## Goals / Non-Goals

**Goals:**
- Make task/method counts, lists, detail routes, and paper filters derive from real published paper references only.
- Keep real paper fallback available for the paper stream when the backend is unavailable.
- Make Research read routes public while keeping user-specific writes and state reads authenticated.
- Clean up visible fallback notices and typography so Research reads as a production research tool.

**Non-Goals:**
- No new backend endpoint names or browser-visible route contracts.
- No automatic LLM or heuristic backfill of missing classifications.
- No migration of existing paper cache files in this change.

## Decisions

- Use one frontend runtime dataset in `real-data.ts` as the source of truth for public Research data. Paper list, task taxonomy, method taxonomy, and detail guards will consume the same normalized papers and notices, so counts and filters stay aligned.
- Treat static catalog entries as presentation metadata only. When a real ref slug matches a catalog item, catalog fields can fill descriptions, labels, groups, related display refs, or areas; a catalog entry without real paper refs must not appear as a user-visible taxonomy item.
- Preserve real refs and remove public heuristic classification. Cache and artifact fallback conversion will read real refs if present and otherwise keep `taskRefs` and `methodRefs` empty. Existing inference helpers can be removed or isolated if no runtime path still needs them.
- Keep read-only Research routes public at middleware level. User-specific BFF routes that pass `NEWSROOM_SESSION_COOKIE` to backend state, notes, materials, selections, or reader events stay authenticated through their own API route behavior.
- Localize notices at the data/result boundary or UI display boundary, but do not show hard-coded English or mojibake strings in Chinese UI.

## Risks / Trade-offs

- Real-only taxonomy can look sparse with the current arXiv cache because many papers lack refs. The mitigation is explicit empty/unclassified states instead of fabricated coverage.
- Backend taxonomy and frontend fallback can briefly differ if one side has stale data. The mitigation is deriving frontend fallback from the same real paper refs and hiding zero-paper items.
- Public read access exposes paper metadata to anonymous users. This matches the Research product decision; write and personal state routes remain protected.
