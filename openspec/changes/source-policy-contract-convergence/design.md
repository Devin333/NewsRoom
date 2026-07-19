## Context

Source collection currently reaches the same policy decisions through several
independent implementations. `business/foundation/primitives/source_ref.py`,
`business/layers/signal/source_processing/url_normalization.py`, and
`infrastructure/external/sources/url_utils.py` canonicalize the same URL with
different blank-input, trailing-slash, query-key, malformed-port, and IPv6
behavior. Business source tools, business health checks, and infrastructure
connectors each own a sliding-window limiter; business tools and infrastructure
connectors also own different retry classifiers. The business and infrastructure
error taxonomies are otherwise nearly identical, while every connector builds
the same `SourceError` envelope locally.

Default `SourceApplicationService` construction already injects one
infrastructure limiter into its connectors and health checker, but the API and
MCP factories can construct a new service for every call. Source tools create a
separate limiter. The resulting quota scope is therefore an accidental property
of the entry point rather than a property of Source runtime composition.

The repository intentionally keeps separate business and infrastructure Source
DTOs because they serve different lifecycles. That is not itself duplication.
The problem is that mappings are repeated across interface services and one
mapping drops `request_ref`, `response_ref`, and `occurred_at`.

This change must preserve public Source payloads, stored artifacts, event replay,
offline connector behavior, and configuration files. The architecture test
normally rejects `infrastructure -> business` imports, with exact module-level
exceptions for approved domain contracts. The current Tool, Research, and event
changes also own dirty composition files, so Source cutover must be staged and
must not introduce an implicit global singleton while waiting for those owners.

## Goals / Non-Goals

**Goals:**

- Make one business-owned URL identity implementation authoritative for all new
  Source identities, including HTML canonical URLs and SourceRef projections.
- Make one business-owned exception taxonomy authoritative while retaining
  explicit, typed connector classification inputs.
- Make the infrastructure Source fetch policy the only implementation of
  limiter and retry algorithms.
- Give each default process composition one thread-safe reservation ledger shared
  by connectors, source tools, health probes, and Research arXiv package/PDF
  adapters.
- Keep business code dependent on Source ports and deterministic decision DTOs,
  not concrete infrastructure classes.
- Preserve every SourceError field through one explicit interface-boundary
  mapper and replace connector-local error envelope constructors with one
  infrastructure adapter.
- Keep historical URL values, ids, refs, artifacts, and replay records readable
  without rewriting them.

**Non-Goals:**

- A distributed or multi-host rate limiter, request queue, or new persistence
  backend.
- Backoff, jitter, circuit breaking, or provider-specific retry scheduling.
- New source providers, parser changes, RAG changes, or Tool authorization work.
- Collapsing business and infrastructure Source DTOs into a generic framework
  model.
- Rewriting stored canonical URLs, hashes, source ids, artifact refs, events, or
  checkpoints.
- A generic `shared/utils` package or a blanket architecture exception.

## Decisions

### 1. Business owns Source URL identity

`business/foundation/primitives/source_ref.py` is the canonical implementation.
Business normalization, tools, projections, quality checks, and SourceRef
construction will call that implementation directly. The signal-layer copy will
be removed after static, dynamic-entry, and public-export audits show that all
repository consumers have moved.

The existing foundation function is also consumed by Research paper,
repository, and paper-card URL fields. Those values are Source identities for
this contract, not unrelated generic URLs. Their persisted fixtures and equality
readers therefore participate in the same single-write/dual-read migration. This
classification is explicit so a change to trailing-slash or query-key behavior
cannot silently alter Research persistence. If a future caller needs URL
semantics that are not Source identity semantics, it must use a deliberately
named domain contract rather than another `canonicalize_url` copy.

`infrastructure/external/sources/url_utils.py` will be a behavior-free Source
adapter to the business contract so standalone `HtmlConnector` construction
cannot silently fall back to a second algorithm. The architecture test will
allow only this exact adapter-to-contract import. Required constructor injection
was considered; it gives a stricter dependency direction, but it would break
direct connector construction across existing adapter consumers unless every
composition owner moved atomically. The exact adapter import is the smaller
explicit exception and contains no policy fallback. Moving the algorithm into a
framework utility was rejected because URL identity is a Source business rule.

The golden write form is deterministic:

- trim input and base URL; blank input produces an empty value;
- resolve a relative input only when an explicit base URL is supplied;
- lowercase scheme and host, bracket IPv6 hosts, remove HTTP port 80 and HTTPS
  port 443, and retain non-default ports;
- remove fragments and a trailing path slash except for the root path;
- remove `utm_*`, `fbclid`, and `gclid` case-insensitively;
- preserve non-tracking query key/value spelling and duplicate pairs, then sort
  pairs deterministically;
- return an unresolved relative value without a base in trimmed,
  fail-preserving form;
- reject malformed absolute URLs, including invalid ports or IPv6 syntax,
  instead of silently inventing a different identity.

New writes use only the golden form. Read-side equality and lookup code may
derive aliases using the two historical canonical forms, but it must try the
stored exact value first and must never rewrite a historical record. The legacy
alias readers are private migration code with fixture-backed removal criteria;
there is no dual-write. Opaque artifact refs and replay ids are never
canonicalized.

### 2. Infrastructure owns limiter and retry execution

`infrastructure/external/sources/fetch_policy.py` remains the only sliding-window
and retry algorithm owner. Business modules retain configuration DTOs, a limiter
port, and immutable decision DTOs so health and tool logic can interpret an
allow/deny result without importing infrastructure. An interface adapter wraps
the canonical infrastructure ledger and maps its decision into the business DTO;
connectors receive the ledger directly while tools and health receive adapters
over that same underlying ledger. Contract tests assert shared reservations, not
Python wrapper identity.

The limiter key is the case-folded canonical provider hostname of the canonical
URL. Scheme, user info, path, query, fragment, and port do not split a domain
quota. The official arXiv metadata host `export.arxiv.org` is explicitly
aliased to `arxiv.org` so metadata, source-package, and PDF calls consume one
provider bucket; other subdomains remain distinct unless a future contract adds
an explicit tested alias. A denial is decided before any network call and is
not retried. The limiter protects its bucket mutation with a lock because one
composition can be used by concurrent HTTP, MCP, worker, and tool calls.

A new Source composition factory at the interface composition boundary creates
one infrastructure fetch policy, one reservation ledger, the business limiter
adapter, the connector router, the health probe adapter, and the source tool
runtime. Stable API/MCP/worker factories close over that composition for the
lifetime of the process. CLI construction uses one composition for the command
lifetime. Explicitly constructed standalone connectors may own a local ledger;
this remains a test and adapter variant, not the default production path.

Retry behavior follows one matrix:

- total attempts are `retry_times + 1`;
- `HTTPError` retries only when its status is in
  `retry_on_status_codes`;
- `TimeoutError`, timeout-shaped `URLError`, and other `URLError` values retry;
- `ValueError` and policy validation failures do not retry;
- other connection/runtime exceptions retain the existing retryable default;
- the final exception carries the actual attempt count, including the first
  attempt when no retry is configured.

Attempt count means invocations of the operation passed to the retry runtime, not
the number of HTTP subrequests that operation performs. Policy construction and
validation happen before the operation and make zero network calls; their errors
do not receive synthetic attempt metadata. Parsing after a successful fetch is
outside the fetch retry boundary.

One logical Source fetch reserves its domain quota exactly once before the retry
loop. Successful and failed logical fetches both consume that reservation;
individual retry attempts do not reserve again. A `RobotsDisallowedError` is a
deterministic non-retryable policy failure, while transport failures encountered
while loading `robots.txt` follow the same HTTP/timeout/URL error matrix as the
content request.

The direct `fetch_text` callable test hook is routed through the same
infrastructure retry policy. Business no longer wraps that hook in a competing
retry loop.

### 3. Business owns taxonomy; infrastructure owns error adaptation

`business/layers/signal/source_processing/error_taxonomy.py` owns Source error
types plus health, workflow, operator, and non-fetch semantic classification.
Connector differences are expressed through an immutable extension input such as
`invalid_config_keywords`; connectors may add diagnostic metadata but may not
replace those decisions.

For fetch and probe exceptions, the infrastructure `SourceFetchRetryDecision` is
the only authority for the final `retryable` value because it has the effective
`retry_on_status_codes` configuration. The shared error factory combines that
decision with the business taxonomy result. Business taxonomy defaults apply
only when no fetch-policy decision is involved. Retry budget exhaustion does not
rewrite the semantic retryable decision. This resolves configured cases such as
retrying 404 or not retrying 503 without creating a second policy table.

`infrastructure/external/sources/errors/taxonomy.py` becomes a behavior-free
adapter/re-export with one exact architecture exception. The health checker and
all connectors use the same classifier. This dependency direction was selected
over copying the rules into infrastructure because taxonomy values affect
business quality, health, and operator behavior.

One infrastructure Source error factory constructs the infrastructure
`SourceError` envelope from a classification, immutable taxonomy extensions, a
request-scoped context, and explicit diagnostics. Context carries phase, URL,
request id, refs, an injectable aware occurrence time, and the original
exception. Diagnostics carry status, attempts, content type, redirect, robots,
and provider fields. Diagnostics cannot overwrite canonical retry, health,
workflow, or operator metadata; conflicts fail closed. The factory also uses the
business-owned policy metadata contract through an exact Source adapter
allowlist. Connector-specific `empty_*` and other already-classified semantic
errors remain explicit inputs, while the repeated envelope and policy projection
are centralized. The unused mutable `FINAL_SOURCE_ERROR_TYPES` copy is removed
unless a complete business-owned immutable set gains a real consumer.

Request-aware adapters attach `request_id` to the errors produced for that call
before exposing them to artifact publication. They do not store request context
on a shared connector. Direct connector calls that have no request object do not
invent an id. The real `SourceApplicationService` collection path and the target
`SyncSourceConnectorAdapter` both receive this per-call enrichment and are
covered by concurrent-request tests; the cache-only `errors_for()` helper is not
treated as evidence that lineage is wired and is retired if no caller remains.

`ArxivSourceConnector` source-package and PDF fetches are Source network
adapters even when called from Research. Default Research composition injects
the same Source reservation ledger. A denial raises a typed Source rate-limit
exception carrying the canonical decision; it does not expose a generic
`ValueError` or call the network. This cutover is reconciled with the active
Research composition owner rather than implemented through a second ledger.

### 4. One explicit mapper crosses Source DTO lifecycles

An interface-boundary Source mapping module owns business-to-infrastructure
definition/policy mapping and infrastructure-to-business item/error mapping.
Callers do not use ad hoc constructors. The separate DTO families remain because
business configuration includes authorization-only fields such as
`allowed_domains`, while infrastructure execution models describe connector
state.

SourceError mapping copies `source_id`, `source_name`, `error_type`,
`error_message`, `url`, explicit or defaulted `retryable`, `request_ref`,
`response_ref`, `occurred_at`, and metadata. Object-to-object mapping preserves
the aware datetime and its offset exactly; persistence readers may normalize to
UTC but must preserve the instant and timezone awareness. Mapping does not
replace the original occurrence time with mapper time, coerce refs to strings,
or infer a new retry decision. Serialized readers parse ISO timestamps and
boolean or documented boolean-string values. Retry precedence is explicit
top-level value, then legacy metadata, then the `True` compatibility default;
new writers emit consistent top-level and metadata booleans.

### 5. Cutover is contract-first and ownership-aware

The change lands in the following order:

1. Commit URL golden, retry matrix, taxonomy parity, SourceError round-trip,
   shared quota, and connector factory regressions.
2. Add canonical adapters, ports, mapper, shared error factory, and process
   composition without changing public transport schemas.
3. Move clean Source callers to the canonical owners.
4. Integrate only the required hunks in concurrently dirty API, Tool, Research,
   or worker composition files after reconciling their current owner changes;
   stage those hunks explicitly.
5. Delete algorithm copies and connector-local constructors only after `rg`, AST
   imports, dynamic entry strings, exports, persisted fixtures, and replay tests
   show the replacement path is complete.

No module-level mutable singleton is introduced as an interim solution. If an
overlapping composition owner cannot be integrated safely, the canonical factory
lands first and the affected entry point remains an explicit, tracked cutover
task rather than receiving a parallel fallback.

## Risks / Trade-offs

- **New URL form changes identity for trailing slashes or mixed-case tracking
  keys** -> Freeze golden cases before cutover, single-write the new form, and
  retain private read aliases for committed historical fixtures.
- **A process-local limiter does not coordinate multiple hosts** -> Document the
  scope and keep distributed limiting outside this change; do not imply a global
  quota in metrics or API text.
- **Sharing one limiter increases contention and exposes data races** -> Lock
  bucket mutation and add deterministic concurrent reservation tests.
- **Exact infrastructure-to-business imports weaken a blanket layer rule** ->
  Allow only named Source adapter modules and named business contract modules;
  retain failure tests for every other import.
- **Connector consolidation can erase useful diagnostics** -> Compare every
  connector's serialized error fixtures before deleting local constructors and
  pass connector fields as explicit factory diagnostics.
- **Retry convergence can change request volume** -> Test status, exception, and
  budget matrices; denial and non-retryable failures remain one network attempt.
- **Dirty composition files can mix unrelated work into the commit** -> Re-read
  current hunks, apply minimal edits, and use path/hunk-specific staging.

## Migration Plan

1. Add golden and parity fixtures while all implementations still exist.
2. Introduce canonical contracts and adapters, then run old/new comparisons in
   tests without dual-writing production data.
3. Switch new URL writes, retry decisions, taxonomy calls, and SourceError
   mapping to canonical owners.
4. Bind default entry points to one Source runtime composition and verify quota
   sharing across connector, tool, and health calls.
5. Confirm historical payload, artifact, and replay fixtures decode unchanged;
   confirm read aliases match old URL forms.
6. Remove duplicate algorithms and constructors after import/export/dynamic
   consumer audits.

Rollback may rebind an entry point to an isolated instance of the canonical
infrastructure limiter while keeping the new canonical contracts and read
aliases. The in-memory window is reset and quota can temporarily become less
strict, which is recorded as an operational rollback effect; there is no limiter
state migration. Rollback must not restore business limiter or retry algorithms,
dual-write URL identities, or rewrite stored records. A URL write cutover
rollback stops new writes at the boundary and keeps both old and new values
readable.

## Open Questions

- Package-external consumers of the two old canonicalization modules cannot be
  proven by repository search; removal requires the public import audit and may
  need one documented deprecation release.
- Real multi-process Redis/Postgres deployments are needed to confirm that the
  documented process quota scope is operationally sufficient; distributed quota
  is a separate design if it is not.
- Final edits to currently dirty composition files depend on reconciling the
  active Tool, Research, and durable-event owners immediately before cutover.
