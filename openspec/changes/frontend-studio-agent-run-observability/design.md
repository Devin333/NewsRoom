## Context

`frontend` is the Task 01-style reader portal and Studio app. It already includes the expected design-system structure, `pnpm`, React Flow, Zustand, lucide, markdown, and shared type/store directories. The implementation must keep the frontend as a UI layer and must not import backend runtime, storage, or artifact modules.

## Goals / Non-Goals

**Goals:**

- Add Studio routes for overview, run list, and run detail.
- Reuse API data where available and fill missing observability fields with deterministic mock data.
- Provide interactive run detail with DAG selection, step detail, inspector tabs, artifact previews, quality checks, and errors.
- Preserve the existing `/runs` pages and shell layout.

**Non-Goals:**

- No backend API changes.
- No real WebSocket, login, source/memory/quality standalone pages, run trigger, or real artifact download.
- No full shadcn, dark-theme, or frontend restructure.

## Decisions

- **Route strategy:** Add `/studio/*` in `frontend`. This satisfies the Task 04 route contract without changing any legacy `apps/web` pages.
- **Data strategy:** Fetch API data from server components via `safeApiGet`; adapt it into Studio models and merge mock detail when fields are missing. This keeps secrets server-only and makes the UI useful before backend observability payloads are complete.
- **Dependency strategy:** Reuse existing `reactflow` for the DAG and `zustand` for inspector selection state. Existing Tailwind, lucide, markdown, and local components are sufficient for the rest.
- **Client/server split:** Pages fetch data on the server. Interactive controls, filters, tabs, and DAG selection live in client components.

## Risks / Trade-offs

- API and mock data can diverge visually → normalize in a single Studio adapter layer and let API identity/status/timestamps win.
- React Flow requires a client boundary and fixed container height → isolate DAG rendering in a client component and import package CSS from the root layout.
- The repository currently has both `apps/web` and `frontend` → implement Task 04 only in `frontend` and avoid modifying `apps/web`.
