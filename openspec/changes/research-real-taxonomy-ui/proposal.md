## Why

Research task and method pages currently mix backend taxonomy, local cache, static catalog entries, and heuristic classification, which makes counts and detail pages look complete even when the displayed relationships are not backed by real paper references. This change makes the Research board truthful and public-readable while preserving the existing `/api/papers...` route surface.

## What Changes

- Make Research task/method taxonomy derive only from published papers that carry real `taskRefs`, `methodRefs`, `benchmarks`, or `implementations`.
- Stop using title, abstract, or tag heuristics to create user-visible task/method relationships in cache or artifact fallback data.
- Keep backend, tracked cache, and artifact paper fallback for the paper stream, but show empty or unclassified taxonomy states when those papers lack real refs.
- Hide zero-paper static taxonomy cards and prevent static catalog-only task/method detail pages.
- Make `/papers`, paper detail/read routes, `/papers/tasks`, and `/papers/methods` public-readable while keeping user-specific write and state APIs authenticated.
- Localize fallback notices and remove Research-specific Comic Sans styling from the reader-facing UI.

## Capabilities

### New Capabilities
- `research-real-taxonomy-ui`: Public Research board behavior, real taxonomy derivation, cache/artifact fallback semantics, and UI truthfulness requirements.

### Modified Capabilities
- None.

## Impact

- Frontend Research data loaders and BFF routes under `frontend/src/lib/papers` and `frontend/src/app/api/papers`.
- Research task/method pages, detail route guards, shared paper row/microbar/sidebar/tab components, and i18n copy.
- Frontend middleware public/protected route handling for `/papers...`.
- Unit tests for real-data fallback, taxonomy pages, detail routes, and Research UI typography.
