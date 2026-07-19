# Source policy contract convergence evidence

## 1. Evidence status

This file records replayable evidence for the current working tree. It is not a
completion declaration.

- Evidence date: `2026-07-19`.
- Baseline inspected: branch `main`, `HEAD 12a504a8`.
- Package version: `0.1.0` from `pyproject.toml`.
- Task ledger at audit start: `0/41`. After the implementation and evidence
  audit, staged-candidate isolation, and verification, the current ledger is
  `38/41` complete and `3/41` open. Tasks `3.7`, `3.10`, and `7.5` remain open. A task is marked complete only
  where the working tree contains both the required implementation/audit and a
  replayable focused test or static evidence.
- The Source core implementation, tests, persistence corpus, and this evidence
  file are isolated as one Source-owned candidate. The commit containing this
  file is replayable core evidence, but it does not complete the open
  composition or production-cutover gates.
- No reproducible pre-fix red log was committed for this change. The proposal,
  design, and regression names describe the prior disagreement, but they do not
  substitute for a recorded red command. This remains a delivery-evidence gap.
- The core URL, retry, taxonomy, error-factory, mapper, and explicitly injected
  shared-ledger paths have passing focused evidence. Default Research binding,
  the production Harness Source-tool ownership decision, complete entry-surface
  quota retention, and final release gates remain open.

Replay the ledger snapshot with:

```powershell
$open = (Select-String -Path 'openspec/changes/source-policy-contract-convergence/tasks.md' -Pattern '^- \[ \]' | Measure-Object).Count
$done = (Select-String -Path 'openspec/changes/source-policy-contract-convergence/tasks.md' -Pattern '^- \[x\]' | Measure-Object).Count
"open=$open done=$done total=$($open + $done)"
```

Current observed result: `open=3 done=38 total=41`. The pre-corpus baseline was
`open=41 done=0 total=41`.

## 2. Requirements to tests

The status column distinguishes passing working-tree evidence from a completed
task. `Core evidenced` means the named deterministic contract is exercised; it
does not waive the open integration, migration, audit, or release gates.

| PRD requirement | OpenSpec requirements | Accountable tasks | Replayable evidence | Current status |
| --- | --- | --- | --- | --- |
| `SRC-001` canonical Source URL identity | `source-canonical-url-default-port`, `source-canonical-url-relative-resolution`, `source-html-canonical-url-normalize` | `1.1`, `2.1`-`2.5` | `tests/contracts/test_source_url_identity_contract.py::test_source_url_golden_contract_is_shared_by_business_and_infrastructure`; malformed URL, `SourceRef`, HTML/tool parity, and historical alias cases in the same file; `tests/contracts/test_source_url_persistence_compatibility.py`; `tests/business/research/test_source_url_identity_compatibility.py` | Core evidenced. Historical readers and deletion audit are working-tree evidence, not yet committed. External package consumers are unconfirmed. |
| `SRC-002` one shared limiter/composition | `source-fetch-rate-limit-policy`, all three `source-pipeline` requirements | `1.3`, `3.2`, `3.5`-`3.10` | `tests/infrastructure/external/sources/connectors/test_fetch_policy.py::test_domain_rate_limiter_reservations_are_atomic_under_concurrency`; logical-reservation, denial, robots, and `export.arxiv.org -> arxiv.org` provider-bucket cases in that file; `tests/interfaces/services/test_source_runtime_composition.py`; `tests/interfaces/services/test_source_health_probe.py`; `tests/interfaces/services/test_source_research_rate_limit.py`; business Source-tool limiter tests | Core composition, canonical Research quota inheritance, and direct connector paths are evidenced. `3.7` and the production Research-factory half of `3.10` remain open; see section 3. |
| `SRC-003` one retry decision owner | `source-fetch-retry-policy` | `1.2`, `3.1`, `3.3`, `3.4`, `3.8`, `3.9` | `tests/infrastructure/external/sources/connectors/test_fetch_policy.py::test_source_fetch_retry_decision_matrix`; configured 404, disabled 503, exhausted/zero budget, validation, parse-boundary, robots, and one-reservation cases; `tests/contracts/test_source_retry_taxonomy_parity.py`; `tests/business/layers/signal/test_source_tools.py` retry cases | Core evidenced. Final full-suite and release gates remain open. |
| `SRC-004` one business taxonomy owner | `source-error-taxonomy` classification and extension requirements | `1.4`, `4.1`, `4.2` | `tests/contracts/test_source_error_taxonomy_parity.py::test_source_taxonomy_golden_matrix_and_adapter_parity`; behavior-free adapter identity test; business and infrastructure taxonomy unit suites | Core evidenced. Legacy keyword signature remains a registered compatibility surface. |
| `SRC-005` explicit live mapper and persisted codec | `source-error-top-level-policy-fields`, `source-error-artifact-refs` | `1.5`, `4.6`, `5.1`-`5.4`, `6.2`, `6.3` | `tests/interfaces/services/test_source_mapping.py` definition/policy, 17-field item, and lossless error tests; `tests/interfaces/services/test_source_request_context.py`; forced-interleaving request metadata and one-shot pending-request tests in `test_feed.py` and `test_protocol.py`; `tests/contracts/test_source_error_persistence_compatibility.py`; `tests/contracts/test_source_url_persistence_compatibility.py`; `business/foundation/models/source_error_normalization.py` is exercised by the persisted tests | Live mapper, request-local connector state, and current persistence corpus are evidenced. The PRD's connector/application/API/MCP/worker/CLI/Source-tool/connector-tool public-payload matrix is not yet fully represented by one cross-surface test, so the PRD-level requirement is not complete. |
| `SRC-006` one connector error factory | shared-construction requirement in `source-error-taxonomy` | `4.3`-`4.6` | `tests/infrastructure/external/sources/errors/test_connector_error_factory_contract.py` covers connector envelope parity, rate-limit envelope, absence of local constructors, and the single infrastructure constructor owner; `tests/infrastructure/external/sources/errors/test_factory.py` covers immutable context/diagnostics and reserved-field rejection | Core evidenced. Final production/export audit and release gates remain open. |

Scenario-level traceability:

| OpenSpec requirement | Primary test oracle(s) | Evidence disposition |
| --- | --- | --- |
| Canonical URL removes default ports | URL golden parameter matrix and malformed URL matrix in `tests/contracts/test_source_url_identity_contract.py` | Passing working-tree contract |
| Canonical URL resolves relative URLs | URL golden matrix, exact-first alias test, Source/Research persistence compatibility tests | Passing working-tree contract; external consumers unconfirmed |
| HTML connector normalizes canonical URLs | Source tool/HTML parity test plus HTML connector malformed-canonical tests | Passing working-tree contract |
| Source connectors enforce per-domain limits | domain-key, arXiv provider alias, atomic concurrency, one-reservation, no-network denial tests in `test_fetch_policy.py`; real metadata-fetch then Research package/PDF denial in `test_source_research_rate_limit.py`; cross-entry composition tests | Passing for canonical ledger and explicit composition |
| Source fetch policy retries transient failures | retry decision/status/budget matrix, validation/parse boundaries, robots transport/denial tests, connector/health/tool parity | Passing working-tree contract |
| Default Source runtime composition shares state | `test_source_runtime_composition.py` and the default-policy Research arXiv denial test | Partial: no default Research owner and no Harness capability decision |
| Default assembly and health use shared ledger | connector/tool/health sequential and concurrent tests; health denial does not increment failure count | Passing for constructed composition |
| Source classification and extensions have one owner | taxonomy golden/parity matrix and adapter identity test | Passing working-tree contract |
| Connectors share error construction | connector factory AST/behavior matrix | Passing working-tree contract |
| Source errors expose top-level policy fields | object mapper tests and persisted reader boolean/time tests | Passing working-tree contract |
| Source error artifacts preserve refs/request ids | artifact/index writer tests, concurrent request-context tests, forced connector response-metadata interleaving, and bounded one-shot protocol pending-state tests | Passing working-tree contract; final committed corpus gate pending |

## 3. Composition gates and known incomplete work

The Source core and production entry owners are intentionally evaluated as
separate gates. An explicit injected-object test is not evidence for a default
production composition.

| Gate | Current code evidence | Missing proof / decision | Disposition |
| --- | --- | --- | --- |
| Core Source composition | `interfaces/services/source_runtime.py` creates one `DomainRateLimiter` and injects it into connectors, Source tool runtime, health/service adapters, and `research_arxiv_connector`; `SourceRuntimeProvider.get()` is lock-protected; connector response metadata uses request-local `ContextVar` state; `BasicSourceHealthManager` serializes in-process state transitions | Latest staged-candidate focused, architecture, compile, smoke, and strict gates pass; final composition integration rerun and commit remain | Open integration/release gate |
| API | `interfaces/api/app.py:313` creates one provider when the default factory is selected | A consecutive-call quota-state test through the real API entry surface | Open part of `3.7` |
| MCP | `interfaces/services/mcp_service.py:127` owns a provider for the service lifetime | A consecutive-call quota-state test through the real MCP entry surface; the unused private `_source_service_factory()` still constructs a standalone service but has no repository caller | Open part of `3.7`; retain/audit the private helper before deletion |
| Worker | `interfaces/services/worker_service.py:195` owns a provider and passes its factory to worker execution | A real consecutive worker-call quota test | Open part of `3.7` |
| CLI | `interfaces/cli/commands/sources.py:352` creates one composition per command handler invocation | A command-lifetime quota test for any command that performs more than one logical Source fetch | Open part of `3.7` |
| Source tool application | `interfaces/services/tool_service.py:36` owns a provider and builds tools from that composition | Entry-level consecutive invocation proof beyond the composition unit test | Open part of `3.7` |
| Research arXiv package/PDF | `SourceRuntimeComposition.research_arxiv_connector` uses the shared ledger and always inherits the canonical Source quota while retaining arXiv-specific timeout/size/retry fields; `test_source_research_rate_limit.py` proves default-policy typed no-network denial and conflicting-policy convergence | `interfaces/services/paper_rag_factory.py:119` creates a new Source runtime when none is injected; `infrastructure/research/document_compiler.py:27` has a standalone `ArxivSourceConnector()` fallback. The default Research production factory is therefore not proven to share the process Source provider. | `3.7` and `3.10` remain open pending `research-runtime-production-composition` integration |
| Harness Source capability (`U2`) | Repository search finds no Harness-owned `SourceRuntimeProvider`, Source `ToolPort`, or canonical production Source registry binding | Tool governance/Harness composition owner must either bind the same provider and record a Harness run, or publish an approved explicit-unsupported capability decision. A second registry or fake path is forbidden. | Blocks `3.7` and overall change completion |

Replay the ownership probe with:

```powershell
rg -n "SourceRuntimeProvider|build_source_runtime_composition|source_tool_runtime|research_arxiv_connector" interfaces business/research infrastructure/research framework -g '*.py'
rg -n "build_business_tool_registry|source\.fetch|SourceRuntimeProvider|source_runtime" framework/harness framework/tool business/research interfaces -g '*.py'
```

The first command locates the interface-owned composition and the two Research
fallbacks described above. The second locates `ToolApplicationService`, but no
production Harness Source composition owner.

## 4. Static, import, export, dynamic-entry, and production-call audits

### 4.1 AST/import boundary

The exact Source architecture permissions are:

- `infrastructure/external/sources/url_utils.py` may import only
  `business.foundation.primitives.source_ref`.
- `infrastructure/external/sources/errors/taxonomy.py` may import only
  `business.layers.signal.source_processing.error_taxonomy`.
- `infrastructure/storage/postgres/repository.py` may import only the persisted
  codec contract `business.foundation.models.source_error_normalization` for
  this Source concern.

These are asserted by `tests/architecture/test_infrastructure_boundary.py`.
There is no directory-prefix or blanket Source allowlist.

Replay:

```powershell
.venv\Scripts\python.exe -m pytest -q tests/architecture
```

Observed on `2026-07-19`: `97 passed, 4 warnings` in the mixed working tree and
`96 passed, 4 warnings` in the Source-only staged candidate. The extra mixed-tree
test belongs to the uncommitted Research adapter allowlist. The warnings are
FastAPI `on_event` deprecations and are unrelated to the Source boundary
assertions.

### 4.2 Duplicate-owner audit

Replay:

```powershell
rg -n "(^|\s)def _?source_error\b|SourceError\s*\(" infrastructure/external/sources -g '*.py'
rg -n "class .*RateLimiter|DomainRateLimiter\(|SourceRateLimit" business infrastructure interfaces -g '*.py'
rg -n "run_with_fetch_retries|decide_source_fetch_retry|is_retryable_fetch_exception" business/layers/signal infrastructure/external/sources interfaces/services -g '*.py'
```

Current findings:

- The `SourceError(...)` constructor search returns only
  `infrastructure/external/sources/errors/factory.py`; the parameterized AST
  guard in `test_connector_error_factory_contract.py` enforces this directory
  invariant.
- `DomainRateLimiter` has one algorithm owner in
  `infrastructure/external/sources/fetch_policy.py`. Connector-local
  `rate_limiter or DomainRateLimiter()` expressions are supported standalone
  adapter construction, not second algorithms; the default composition injects
  one shared ledger.
- Fetch retry execution and classification are owned by `fetch_policy.py`.
  Interface adapters call `run_with_fetch_retries`; business retains only the
  port/decision DTO and taxonomy projection.

### 4.3 URL import/export and dynamic-entry audit

The deleted signal algorithm was never exported from
`business/layers/signal/source_processing/__init__.py`. The current live tree
contains no production import or dynamic-entry string for that module. The only
remaining historical algorithms are private functions reached by
`source_url_read_aliases`.

Replay from the repository root (exit code `1` means no match):

```powershell
rg -n "business\.layers\.signal\.source_processing\.url_normalization|source_processing\.url_normalization" business infrastructure interfaces framework scripts configs pyproject.toml -g '*.py' -g '*.toml' -g '*.yaml' -g '*.yml'
rg -n "infrastructure\.external\.source_adapters|from infrastructure\.external import|import infrastructure\.external(\s|$)" business infrastructure interfaces framework scripts configs pyproject.toml -g '*.py' -g '*.toml' -g '*.yaml' -g '*.yml'
rg -n "entry_points|console_scripts|import_module|module:|callable:" pyproject.toml configs scripts -g '*.py' -g '*.toml' -g '*.yaml' -g '*.yml'
```

Observed findings:

- The first two searches return no live-tree consumers.
- The configured package entry point is only
  `news = "interfaces.cli.news:main"`; no Source compatibility module is loaded
  by a dynamic entry string.
- Repository search cannot prove absence of package-external Python consumers.
  Therefore the two public infrastructure facades remain registered and are
  not safe to delete solely from this audit.

### 4.4 Legacy taxonomy signature audit

Production connector, tool, and health callers pass the immutable
`SourceTaxonomyExtension`. The old
`classify_source_exception(..., invalid_config_keywords=...)` keyword remains
accepted, and `tests/infrastructure/external/sources/errors/test_taxonomy.py`
still calls it directly. Replay with:

```powershell
rg -n "invalid_config_keywords\s*=" business infrastructure interfaces tests -g '*.py'
rg -n "classify_source_exception\(" business infrastructure interfaces tests -g '*.py'
```

The signature is therefore a compatibility surface, not removable dead code.

## 5. Migration and persistence evidence

Migration follows expand -> dual-read -> single-write cutover -> compatibility
window -> delete. The working tree contains a disk-backed corpus under
`tests/fixtures/source_policy_persistence/` for historical Source records,
Source item/error artifacts and `source_artifacts/index.json`, Source item/error
events, and replay checkpoints.

The contract is:

- readers try the exact stored URL first and may derive both historical aliases;
- historical URL, id, hash, artifact refs, event payloads, checkpoint state,
  SourceError refs, retry semantics, and occurrence instant are not rewritten;
- new Source identity writes emit only the golden URL and never persist alias
  arrays or a second identity;
- object mapping preserves the original aware offset; persisted readers accept
  documented boolean strings and preserve the instant;
- rollback readers are read-only and fixture byte comparisons detect rewrites.

Primary replay command:

```powershell
.venv\Scripts\python.exe -m pytest -q `
  tests/contracts/test_source_url_identity_contract.py `
  tests/contracts/test_source_url_persistence_compatibility.py `
  tests/business/research/test_source_url_identity_compatibility.py `
  tests/contracts/test_source_error_persistence_compatibility.py
```

Tasks `6.2` and `6.3` were marked complete after the disk corpus passed its
focused reader/writer suite. The corpus is committed with the Source core slice
containing this evidence file; the release claim remains open until the pending
composition gates are integrated and the final gate is rerun from that state.

## 6. Rollback qualification

The newer phase-20 PRD rollback contract takes precedence over the design text
where they differ: rollback must select the previous qualified composition while
retaining one canonical shared limiter. It must not restore business limiter or
retry algorithms, introduce a second ledger, dual-write identities, or rewrite
persisted records. Resetting the process-local in-memory window can temporarily
make quota less strict and must be recorded as an operational effect.

| Required field | Current value |
| --- | --- |
| `trigger_metric` | Required invariants are zero shared-ledger violations, zero attempts beyond the retry matrix, and zero URL/taxonomy/persistence golden mismatches. Production counters for these invariants are not yet demonstrated. |
| Observation window / threshold | Test threshold is zero failures. A production observation window is not yet assigned. |
| `decision_owner` / on-call | Source runtime owner is accountable; a named release/on-call owner is not yet recorded. |
| `rollback_target` | Not yet set to a qualified version/commit/flag. This blocks production cutover. |
| Data compatibility | Keep exact-first historical alias reads and persisted SourceError codec; do not rewrite records/events/checkpoints or dual-write identities. |
| `post_rollback_oracle` | URL golden/persistence, quota/retry/robots, taxonomy/factory, mapper/request-context, architecture, compile, and smoke suites must pass. |
| `max_recovery_time` | Not yet assigned. |
| Rehearsal | No recorded or fault-injection rollback rehearsal is present. |

The unset fields and missing rehearsal are explicit release blockers; they are
not waived by focused unit tests.

## 7. Compatibility registry

Current package version is `0.1.0`. `expires_release=0.2.0` means the surface
must be removed by that release or renewed by an explicit OpenSpec/PRD decision.
Missing telemetry blocks early deletion; it does not extend expiry implicitly.

| Surface | Owner | `introduced_release` / commit | `expires_release` | Removal condition | Telemetry | Evidence | `kill_switch_retirement` |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `business.foundation.primitives.source_ref.source_url_read_aliases` plus private `_canonicalize_url_foundation_v1` and `_canonicalize_url_signal_v1` | Source identity owner (`business/foundation/primitives/source_ref.py`) | `0.1.0` target; introduced by the Source core commit containing this evidence file | `0.2.0` | One full compatibility window; committed Source/Research/artifact/event/checkpoint corpus proves no historical values require either alias; package/external consumer audit is complete; exact new writes remain golden | No runtime alias-hit telemetry is implemented; fixture coverage only, so removal is blocked | URL identity/persistence and Research persistence tests; `rg source_url_read_aliases` enumerates current readers | No runtime switch exists. Remove the alias reader and both private algorithms together after the removal conditions pass. |
| `infrastructure/external/source_adapters.py` public facade | Infrastructure Source adapter owner | pre-`0.1.0`; migration commit `b9adf598` (`git log --follow`) | `0.2.0` | Repository, documentation, dynamic-entry, and package-consumer audits show zero users for one release; consumers use `infrastructure.external.sources` or narrower modules | No invocation telemetry is implemented; repository `rg` currently returns no consumers, which is insufficient for package-external deletion | `git log --follow -- infrastructure/external/source_adapters.py`; live-tree import search in section 4.3 | No switch exists. Retire the facade export file after the compatibility window; do not add a fallback route. |
| `infrastructure/external/__init__.py` top-level Source re-exports | Infrastructure Source adapter owner | pre-`0.1.0`; introduced/migrated by commit `b9adf598` | `0.2.0` | Same five-way consumer audit succeeds and all supported imports use the owning subpackage; one deprecation release has elapsed | No invocation telemetry is implemented; repository `rg` currently returns no consumers | `git log --follow -- infrastructure/external/__init__.py`; current `__all__`; live-tree import search in section 4.3 | No switch exists. Remove only the compatibility re-exports after consumers migrate; do not duplicate implementation. |
| `classify_source_exception(..., invalid_config_keywords=...)` legacy keyword | Business Source taxonomy owner | pre-`0.1.0`; introduced by commit `f7e9f146` | `0.2.0` | Internal callers and tests use `SourceTaxonomyExtension`; package-consumer audit/deprecation window completes; passing parity matrix proves identical supported behavior | No keyword-use telemetry is implemented; one repository test intentionally remains a consumer | `git log -S invalid_config_keywords`; searches in section 4.4; taxonomy parity tests | No switch exists. Remove the keyword and its conflict branch after the last compatibility consumer migrates. |

Registry status: `overdue=0` for package version `0.1.0`; all four entries are
still active and none is approved for deletion.

### Permanent architecture adapters (not temporary compatibility)

The following modules are intentionally excluded from the expiry registry:

- `infrastructure/external/sources/url_utils.py` is the permanent behavior-free
  infrastructure adapter to the business Source URL identity contract.
- `infrastructure/external/sources/errors/taxonomy.py` is the permanent
  behavior-free adapter/re-export to the business Source taxonomy contract.

Their permanence follows the OpenSpec design dependency decision and is guarded
by exact AST/import tests. They contain no fallback algorithm and must not be
misclassified as a temporary compatibility layer.

## 8. Focused verification record

Executed with the repository virtual environment on `2026-07-19`:

```powershell
# Complete Source-focused aggregate across business/foundation/signal,
# connectors/errors, artifact/local/Postgres persistence, interface services,
# HTTP/MCP/worker/CLI/tool entry surfaces, and Source contracts.
$paths = @(
  'tests/business/foundation/test_source_models.py',
  'tests/business/foundation/test_source_error_normalization_contract.py',
  'tests/business/foundation/test_source_registry.py',
  'tests/business/foundation/registry/test_source_registry_ai_community_validation.py',
  'tests/business/layers/signal',
  'tests/business/research/test_source_url_identity_compatibility.py',
  'tests/business/research/code_repository/test_code_repo_models.py',
  'tests/business/test_tool_registry.py',
  'tests/infrastructure/external/sources',
  'tests/infrastructure/storage/test_artifact_index_factory.py',
  'tests/infrastructure/storage/test_artifact_store.py',
  'tests/infrastructure/storage/test_local_json_persistence_adapter.py',
  'tests/infrastructure/storage/test_persistence_records.py',
  'tests/infrastructure/storage/test_persistence_repository_compat.py',
  'tests/infrastructure/storage/postgres/test_postgres_artifact_index.py',
  'tests/infrastructure/storage/postgres/test_postgres_repository.py',
  'tests/interfaces/services/test_source_application_service.py',
  'tests/interfaces/services/test_source_health_probe.py',
  'tests/interfaces/services/test_source_mapping.py',
  'tests/interfaces/services/test_source_request_context.py',
  'tests/interfaces/services/test_source_research_rate_limit.py',
  'tests/interfaces/services/test_source_runtime_composition.py',
  'tests/interfaces/services/test_source_service_batch_fetch.py',
  'tests/interfaces/services/test_source_service_fetch_source.py',
  'tests/interfaces/services/test_mcp_application_service.py',
  'tests/interfaces/services/test_tool_service.py',
  'tests/interfaces/services/test_worker_app_service.py',
  'tests/interfaces/services/test_paper_rag_factory.py',
  'tests/interfaces/api/test_api_contracts.py',
  'tests/interfaces/api/test_api_mcp.py',
  'tests/interfaces/api/test_api_mcp_sdk_surface.py',
  'tests/interfaces/api/test_api_router_parity.py',
  'tests/interfaces/api/test_final_target_routes.py',
  'tests/interfaces/api/test_http_api_foundation.py',
  'tests/interfaces/cli/test_sources_commands.py',
  'tests/interfaces/cli/test_sources_fetch_commands.py',
  'tests/interfaces/cli/test_tools_commands.py',
  'tests/interfaces/cli/test_mcp_commands.py',
  'tests/interfaces/cli/test_cli_command_registration.py',
  'tests/interfaces/cli/test_cli_news_entrypoint.py',
  'tests/interfaces/test_contract_models.py',
  'tests/contracts/test_source_error_persistence_compatibility.py',
  'tests/contracts/test_source_error_taxonomy_parity.py',
  'tests/contracts/test_source_retry_taxonomy_parity.py',
  'tests/contracts/test_source_url_identity_contract.py',
  'tests/contracts/test_source_url_persistence_compatibility.py'
)
$env:PYTHONDONTWRITEBYTECODE = '1'
& .venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --tb=short -rA $paths
# 790 passed, 4 skipped, 0 failed; 220 warnings
```

The `790` result is the complete mixed-working-tree aggregate before the final
Source-owned staging split. The staged Source core candidate was then built
from `git write-tree` plus `git commit-tree` in a detached temporary worktree
and verified independently:

```powershell
# Same $paths selection against the staged-only candidate.
& F:\github\NewsRoom\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --tb=short -rA $paths
# 787 passed, 4 skipped, 0 failed; 212 warnings

& F:\github\NewsRoom\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider tests/architecture
# 96 passed, 4 warnings

& F:\github\NewsRoom\.venv\Scripts\python.exe -m scripts.dev compile
# passed

& F:\github\NewsRoom\.venv\Scripts\python.exe -m scripts.dev smoke
# 1192 passed, 23 skipped, 12 warnings; Source validation passed

openspec validate source-policy-contract-convergence --strict
# valid

openspec validate --all --strict
# 180 passed, 0 failed

git diff HEAD^ HEAD --check
# passed
```

The staged candidate intentionally has fewer tests than the mixed tree because
Research adapter, framework safety, durable event, API safety, and worker lease
hunks were excluded. The difference is an ownership split, not deselection of a
failing Source test.

The four skips are Windows `WinError 1314` environment-only skips for symlink
escape tests in `test_source_indexing.py` and `test_artifact_store.py`. They do
not hide a Source policy failure, but the symlink branches remain unexecuted in
this environment. The aggregate and architecture gates must be rerun after the
remaining composition integration changes before final release evidence is
claimed.

```powershell
.venv\Scripts\python.exe -m pytest -q tests/contracts/test_source_url_persistence_compatibility.py tests/contracts/test_source_error_persistence_compatibility.py
# 12 passed

.venv\Scripts\python.exe -m pytest -q tests/contracts/test_source_url_identity_contract.py tests/contracts/test_source_url_persistence_compatibility.py tests/business/research/test_source_url_identity_compatibility.py tests/contracts/test_source_error_persistence_compatibility.py
# 42 passed

.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --tb=short `
  tests/infrastructure/external/sources/connectors `
  tests/interfaces/services/test_source_research_rate_limit.py `
  tests/interfaces/services/test_source_runtime_composition.py `
  tests/business/layers/signal/source_health/test_health_manager.py
# 151 passed after request-local connector metadata, bounded protocol pending
# state, serialized health transitions, canonical arXiv provider bucketing, and
# real metadata-fetch then package/PDF no-network denial coverage

.venv\Scripts\python.exe -m pytest -q tests/contracts/test_source_retry_taxonomy_parity.py tests/contracts/test_source_error_taxonomy_parity.py tests/infrastructure/external/sources/errors/test_connector_error_factory_contract.py tests/interfaces/services/test_source_mapping.py tests/contracts/test_source_error_persistence_compatibility.py tests/interfaces/services/test_source_request_context.py
# 50 passed

.venv\Scripts\python.exe -m pytest -q tests/architecture
# 97 passed, 4 warnings
```

The system interpreter was not used as evidence because it lacks repository
dependencies such as `fastapi`.

Still required before change completion can be claimed:

- rerun the focused aggregate and architecture suite after the remaining
  composition integration changes;
- complete the entry/Research/Harness gates in section 3;
- rerun compile, smoke, strict OpenSpec, and diff checks after the remaining
  composition integration changes;
- fill the rollback owner/target/window/recovery fields and record a rehearsal.

## 9. Unconfirmed items

| Item | Why it is unconfirmed | Verification needed / default disposition |
| --- | --- | --- |
| Package-external consumers of old URL/facade/taxonomy surfaces | Repository `rg`, AST, exports, and dynamic-entry searches cannot inspect installed downstream packages | Collect release telemetry or consumer confirmation and preserve the registered surfaces through `0.2.0` unless an explicit renewal/removal decision is approved. |
| Default Research shares the process Source ledger | Only explicit injection is tested; default factories still create/fallback to standalone Source adapters | Integrate through `research-runtime-production-composition`, assert the real object graph and typed no-network denial for package and PDF calls. |
| Production Harness Source capability and owner (`U2`) | No canonical Harness `ToolPort`/registry binding or explicit unsupported decision is recorded | Tool/Harness owner must bind the same provider and record a run, or publish an explicit unsupported decision in an accountable child change. |
| Process-level quota sufficiency across hosts | This change intentionally implements a process-local ledger | Qualify real deployment topology separately; do not claim distributed quota. Keep the current process-scope contract. |
| Live arXiv behavior | Ordinary gates intentionally avoid credentials/network | Run a separate credential-gated E2E without logging secrets; absence does not waive deterministic/default-composition contracts. |
| Real backend persistence parity | The Source corpus proves model/artifact/event/checkpoint readers, not Redis/Postgres/Qdrant service behavior | Run the relevant service-gated backend contract only if this change modifies or declares support for that backend; otherwise make no new backend claim. |
| Rollback operational readiness | No qualified rollback target, on-call, observation window, recovery time, or rehearsal is recorded | Do not perform production cutover until section 6 is complete. |
