## Why

Research now uses real paper data, but several UI states still sound like implementation failures, duplicate taxonomy labels can make the catalog look inconsistent, and the mobile layout delays the primary paper feed. This change makes the Research board easier to trust and faster to use without fabricating data.

## What Changes

- Replace backend/API/fetch failure copy with product-facing degraded data states.
- Merge equivalent task and method taxonomy slugs before public aggregation.
- Move the mobile paper feed ahead of secondary taxonomy navigation and expose taxonomy as compact chips.
- Hide unavailable paper metrics instead of showing `N/A` at the same weight as verified counts.
- Make paper cards expose clear Preview, Read, PDF, and Code actions.
- Defer PDF thumbnail rendering beyond the first visible rows.
- Put related papers before benchmark and relation panels on task/method detail pages.
- Fix duplicate React keys in benchmark result rendering.
- Add lightweight paper-feed filters for PDF, code, benchmark, and citation availability.
- Add taxonomy sorting and clearer real-data source wording.
- Add local paper workspace actions for reading list, comparison, and read-later triage.

## Impact

- Frontend Research UI components under `frontend/src/components/papers`.
- Research data normalization and taxonomy aggregation under `frontend/src/lib/papers/real-data.ts`.
- Research page tests and detail drawer tests.
