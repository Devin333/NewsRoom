## Overview

The Reader route should optimize for time to first useful content without lying about available data. The implementation keeps compiled documents as the preferred path, but gives backend document/status calls explicit budgets and lets the existing paper cache produce a truthful status payload when the visual compiler is slow or unavailable.

On the client, compiled documents still adapt through `paperDocumentToOpenReader`, but the Open Reader mounts a bounded initial set of sections and expands the rest in idle slices. Navigation from the floating table of contents expands up to the requested section before scrolling, so users do not lose direct access to later content.

## Server Loading

- Add small timeout helpers in `server-loader.ts` and pass `AbortSignal` to `safeApiGet`.
- Use a short document timeout for compiled document calls and a shorter status timeout for compile status calls.
- Treat timeout/abort as a normal degraded result that produces diagnostics through the existing fallback status shape.
- Resolve slugs through `getPaperById` as before; if the first document call times out, do not perform another slow document call for the resolved id during the same request.
- Continue returning `null` for unknown papers and unpublished compiled payloads.

## Client Rendering

- Build paragraphs, TOC, and visual grouping once per payload as today.
- Derive a stable ordered section list and render only an initial section window.
- Expand the window using `requestIdleCallback` when available and `setTimeout` fallback otherwise.
- When the user navigates to an unrendered TOC item, synchronously expand the window to include that item and scroll after React has mounted it.
- Keep references visible once all sections are rendered; this avoids pushing a large reference list into the first paint for long papers.
- Defer `fetchReaderMaterials` with the same idle scheduler because it is personal/non-critical sync data, not required to read public paper text.

## Testing

- Server loader tests cover document API timeout/fallback and confirm a timed-out slug lookup does not retry the document endpoint.
- Open Reader tests cover initial section limiting, idle expansion, direct TOC navigation to hidden sections, and deferred material loading.
- Existing document reader tests continue covering compiled visual blocks, status gates, source previews, and interactions.

## Risks

- Tests running in jsdom do not fully model browser layout. Use explicit DOM assertions and mocked idle callbacks for deterministic coverage.
- Progressive rendering can hide later references briefly. This is intentional for first paint; direct navigation expands the target content immediately.
