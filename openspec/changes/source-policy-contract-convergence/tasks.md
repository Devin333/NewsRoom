## 1. Contract Baseline And Ownership Guards

- [x] 1.1 Add shared Source URL golden fixtures covering blank, unresolved relative, fragment, trailing slash, tracking-key case, duplicate query pairs, default/custom ports, IPv6, userinfo removal, and malformed absolute rejection.
- [x] 1.2 Add a retry exception/status/budget matrix that fails against the business retry copy, covers allowed 404 and disabled 503, and distinguishes operation invocations from zero-attempt validation and post-fetch parse failures.
- [x] 1.3 Add deterministic shared-quota tests spanning connector, Source tool, and health probe calls, including concurrent reservations and no-network-on-denial assertions.
- [x] 1.4 Add a concrete taxonomy golden matrix plus old/new parity fixtures for fetch, parse, normalize, dedup, rank, probe, policy exceptions, and connector extension inputs.
- [x] 1.5 Add SourceError mapper and serialized-reader round-trip fixtures with explicit refs, nested metadata, boolean strings, retry precedence, and aware non-UTC `occurred_at` values.
- [x] 1.6 Extend architecture tests with exact Source adapter-to-business contract permissions and retain rejection of every unlisted `infrastructure -> business` import.

## 2. Canonical Source URL Identity

- [x] 2.1 Implement the golden URL write contract in `backend/foundation/primitives/source_ref.py` and make SourceRef identity construction consume it.
- [x] 2.2 Add private read-side aliases for both historical URL forms, exact-value-first lookup, and no-rewrite behavior for persisted ids, hashes, and artifact refs.
- [x] 2.3 Move business normalization, tools, projections, citation/quality checks, and tests to the canonical business implementation; add persisted compatibility fixtures for Research paper, repository, and paper-card Source URLs.
- [x] 2.4 Convert `infrastructure/external/sources/url_utils.py` to a behavior-free adapter and prove HTML connector parity with business and tool entry points.
- [x] 2.5 Audit public exports, dynamic entry strings, and package-external documentation, then remove the signal-layer algorithm copy or record a time-bounded deprecation if an external consumer is confirmed.

## 3. Fetch Policy Runtime And Composition

- [x] 3.1 Keep limiter ports and immutable decision DTOs in business while removing the business sliding-window algorithm and broad retry classifier.
- [x] 3.2 Make infrastructure `DomainRateLimiter` the thread-safe limiter owner with one canonical hostname key and deterministic clock injection.
- [x] 3.3 Make infrastructure retry classification and its decision DTO authoritative for fetch/probe retryability across HTTP status, timeout, `URLError`, `ValueError`, unknown exception, zero-budget, and exhausted-budget cases.
- [x] 3.4 Route direct `fetch_text` test hooks and Source tool fetches through the infrastructure retry runtime exactly once.
- [x] 3.5 Add an explicit interface Source runtime composition that creates one fetch policy, reservation ledger, business decision adapter, connector router, health probe adapter, and Source tool runtime without module-global mutable state.
- [x] 3.6 Give default connector, Source tool, and health checker paths access to the same underlying reservation ledger while retaining explicit standalone connector isolation.
- [x] 3.7 Bind API, MCP, worker, CLI, Source-tool registry, and Research arXiv package/PDF factories to stable Source compositions for their process or command lifetime; record Harness Source capability as explicitly unsupported until a canonical Harness-owned ToolPort is composed; verify consecutive calls retain quota state.
- [x] 3.8 Verify rate-limit denials do not call a fetcher, consume retry budget, or increment Source health failure counts.
- [x] 3.9 Verify each logical fetch reserves quota once across retries and distinguish deterministic robots denial from retryable robots transport failure.
- [x] 3.10 Replace generic arXiv package/PDF rate-limit `ValueError` with a typed canonical denial and prove its Research composition shares the Source ledger without network access.

## 4. Canonical Taxonomy And Error Construction

- [x] 4.1 Add an immutable business taxonomy extension input and make one business classifier own all classification flags and final Source error types.
- [x] 4.2 Convert the infrastructure taxonomy module to a behavior-free adapter and replace health-probe classification with the canonical classifier.
- [x] 4.3 Add one infrastructure SourceError factory with immutable taxonomy extensions, request-scoped context, typed diagnostics, reserved-policy-field conflict checks, injectable aware time, refs, and occurrence preservation.
- [x] 4.4 Migrate arXiv, community, feed, GitHub, Hacker News, HTML, manual, and Reddit connectors to the shared factory without changing their connector-specific parse or diagnostic behavior.
- [x] 4.5 Add a parameterized connector contract test proving serialized envelope parity and remove all connector-local `_source_error` constructors.
- [x] 4.6 Make `SourceApplicationService` collection and target connector adapters attach per-call request ids without shared mutable context; retire the cache-only `errors_for()` helper if its production-call audit remains empty.

## 5. Explicit Source DTO Mapping

- [x] 5.1 Add one interface-boundary Source mapper for business-to-infrastructure definitions/policies and infrastructure-to-business raw items/errors.
- [x] 5.2 Preserve every SourceError field, ref representation, nested metadata value, retry precedence, occurrence instant, and timezone awareness; parse serialized bool/datetime values and preserve object-mapper offsets.
- [x] 5.3 Migrate Source service and Source tool runtime callers to the mapper and remove their ad hoc mapping functions.
- [x] 5.4 Add contract tests showing business and infrastructure DTOs remain intentional lifecycle variants while producing stable public Source payloads.

## 6. Compatibility Cutover And Duplicate Removal

- [x] 6.1 Re-read active Tool, Research, event, API, and worker changes immediately before composition edits; reconcile overlapping hunks and stage only Source-owned changes.
- [x] 6.2 Add persisted Source record, artifact index, event, and replay fixtures proving historical URL identities and SourceError payloads decode unchanged.
- [x] 6.3 Verify new writes use only the golden URL form and that rollback/read paths never dual-write or rewrite historical records.
- [x] 6.4 Run `rg`, AST import/export, dynamic-entry, and production-call audits before deleting URL, limiter, retry, taxonomy, mapper, and connector-constructor copies.
- [x] 6.5 Document any confirmed external compatibility export with owner, telemetry or fixture evidence, removal condition, and expiry; retain no undocumented compatibility layer.

## 7. Verification And Delivery

- [x] 7.1 Run focused Source business, infrastructure connector, interface service, artifact, health, tool, and contract suites.
- [x] 7.2 Run `tests/architecture` and confirm no blanket Source boundary exception was introduced.
- [x] 7.3 Run `python -m scripts.dev compile` and mandatory `python -m scripts.dev smoke`.
- [x] 7.4 Run `openspec validate source-policy-contract-convergence --strict`, `openspec validate --all --strict`, and `git diff --check`.
- [x] 7.5 Record verification evidence, requirements-to-tests traceability, environment-only skips, migration checks, and rollback checks before archiving the change.
