## 1. OpenSpec

- [x] 1.1 Validate the `research-real-taxonomy-ui` OpenSpec change with strict validation.

## 2. Data Contract

- [x] 2.1 Refactor Research paper runtime data so backend, cache, and artifact sources preserve only real task/method refs.
- [x] 2.2 Derive task and method taxonomy from published paper refs and enrich matching slugs with catalog metadata only.
- [x] 2.3 Remove static catalog-only taxonomy fallback from list and detail route behavior.

## 3. Public Read And UI

- [x] 3.1 Make Research read routes public while keeping user-specific paper state and interaction APIs authenticated.
- [x] 3.2 Update task and method pages to hide zero-paper items and show truthful localized empty/degraded states.
- [x] 3.3 Remove Research-specific Comic Sans inline styling and fix mojibake fallback copy.

## 4. Tests And Verification

- [x] 4.1 Add or update real-data tests for real-only taxonomy and catalog metadata enrichment.
- [x] 4.2 Update task/method page, detail route, and Research typography tests.
- [x] 4.3 Run targeted frontend tests, typecheck, strict OpenSpec validation, and backend compile after dependencies are available.
- [x] 4.4 Commit the completed code and OpenSpec changes.
