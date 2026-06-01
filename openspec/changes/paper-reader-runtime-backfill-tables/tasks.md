## 1. Runtime Contract

- [x] 1.1 Add OpenSpec requirements for real published paper backfill, queue expansion, scheduling, Studio trigger, and structured table fidelity.
- [x] 1.2 Validate the change with `openspec validate paper-reader-runtime-backfill-tables --strict`.

## 2. Backend Runtime

- [x] 2.1 Add a visual compile backfill planner that scans published papers and returns only papers needing compilation.
- [x] 2.2 Add `papers.visual_compile_backfill` worker task and enqueue API that expands candidates into `papers.visual_compile` tasks.
- [x] 2.3 Add backend ops route and local background fallback for triggering backfill when the worker queue is unavailable.
- [x] 2.4 Add schedule helper/CLI support for periodic visual compile backfill.
- [x] 2.5 Ensure local ingest fallback sends newly published paper IDs through the same visual compiler runtime when Redis is unavailable.

## 3. Studio UI

- [x] 3.1 Add Next.js BFF and API client support for triggering visual compile backfill.
- [x] 3.2 Add Studio Paper Reader Operations controls and localized copy for backfill status.

## 4. Table Fidelity

- [x] 4.1 Add tests proving structured table models preserve row/cell colors, rules, `cmidrule`, `multicolumn`, and `multirow`.
- [x] 4.2 Ensure Asset Gate blocks table assets without structured table metadata.

## 5. Verification

- [x] 5.1 Run targeted backend and frontend tests for worker/API/visual compiler/ops panel.
- [x] 5.2 Run `python -m scripts.dev compile`, frontend typecheck if touched, and OpenSpec strict validation.
- [x] 5.3 Commit all code and OpenSpec changes.
