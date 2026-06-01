## Why

Research Reader currently waits for the full compiled document API before rendering and then mounts the entire Open Reader body at once. On slow compiler/storage paths or long papers this makes the read route feel blank or heavy before the user can start reading.

## What Changes

- Add a bounded wait contract for the server-side Reader document loader so slow compiled-document endpoints fall back to a truthful lightweight payload instead of blocking the route indefinitely.
- Keep the existing `/papers/{slug}/read` route and document API contracts unchanged while making degraded Reader states visible quickly.
- Render compiled Open Reader documents progressively on the client: the first sections are visible immediately, and later sections expand during idle time or direct navigation.
- Defer non-critical reader material synchronization until after the first paint/idle window so hydration competes less with reading content.
- Preserve real-data behavior: no fake document body, no fabricated reader material, and no changed access control semantics.

## Capabilities

### New Capabilities
- `research-reader-performance`: Research Reader bounded server loading, progressive Open Reader rendering, deferred non-critical material sync, and user-visible degraded states.

### Modified Capabilities

## Impact

- Frontend Reader server loader under `frontend/src/lib/paper-reader`.
- Open Reader page rendering and utilities under `frontend/src/components/papers/open-reader`.
- Paper Reader page tests, route tests, and server loader tests.
- OpenSpec validation only; no backend API, route shape, or dependency changes.
