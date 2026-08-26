# Runtime Production Composition Evidence

## Evidence Status

This file is the qualification ledger for `harness-runtime-production-composition`. The current snapshot records implementation evidence and explicit blockers; it is not a production qualification sign-off. An entry is not production evidence until it contains the exact commit, command, environment capability, result classification, and immutable receipt/event reference required below.

## Baseline Snapshot

| Field | Value |
| --- | --- |
| Baseline date | 2026-08-26 |
| Baseline commit | `6bbf3eed` |
| `harness-runtime-execution-safety` | 23/28, in progress |
| `durable-event-runtime` | 53/55, in progress |
| `harness-workflow-graph-runtime` | 99/100, in progress |
| `model-aware-llm-context-preflight` | 28/34, in progress |
| `source-policy-contract-convergence` | 41/41, complete |
| Docker daemon on authoring host | unavailable at baseline; not a production qualification pass |

## Implementation Snapshot

| Field | Value |
| --- | --- |
| Snapshot date | 2026-08-26 |
| Implementation code commit | `9cf2a46d` |
| Research composition manifest | `newsroom-runtime`, version `1` |
| Composition fingerprint | `sha256:6f59871e2e427717ac9d9df6993bbcc9ad8e9ff5593d5247412d51b39b1e460b` |
| Policy fingerprint | `sha256:3263923c9ddb6fc67d29ec2dcb2046151cf5937e537b61180316abd14ca3580d` |
| Provider fingerprint | `sha256:ec5b242b5643d44470cff3dff6f4851bf173537c1f54926adf871b56aaa4a3e5` |
| Registered execution profiles | `runtime-trusted-in-process` (`trusted_in_process`), `research-parser-marker` and `research-parser-mineru` (`external_process`) |
| Registered provider | `docker` |
| Production vertical slice | Research parser -> `ResearchParserExecutionAdapter` -> `ExecutionEnvironmentRegistry` -> Docker provider |
| API readiness behavior | optional composition verifies manifest integrity; role-required provider/port drift returns typed `503`, while catalogued-but-optional providers remain admission-gated |
| Qualification state | implementation evidence only; no real Docker receipt/event or external release signature |

## Predecessor Handoff

`harness-runtime-execution-safety` tasks 5.1-5.4 remain open predecessor qualification work. This change reuses the completed execution-environment (2.1-2.6), child-supervisor (3.1-3.6), and runtime-event (4.1-4.6) contracts, but does not claim the pending end-to-end evidence as complete.

| Predecessor item | Handoff in this change | Status |
| --- | --- | --- |
| 5.1 Restart, timeout, child-loss, cancellation, and side-effect recovery | Crash-Recovery Matrix below retains each required scenario as pending. | explicitly handed off |
| 5.2 Production caller scan | Composition Capability Matrix tracks remaining child, MCP, worker, and CLI callers. | explicitly handed off |
| 5.3 Focused/compile/smoke/strict validation | Test and Deployment Ledger records only completed local contract checks. | partially evidenced; broader gate pending |
| 5.4 Deployment capability and rollback evidence | Docker, secret, and independent release blockers remain explicit. | blocked pending target environment |

## Capability/Profile Registry Contract

| Profile or boundary | Declared contract | Admission outcome |
| --- | --- | --- |
| `runtime-trusted-in-process` | `trusted_in_process`; no external provider or isolation claim | admitted only for deterministic in-process work |
| `sandboxed_process` | Framework-owned profile mode and admission contract; the current manifest declares an empty catalog | no sandboxed profile is enabled until a provider can prove its requested controls |
| `research-parser-marker` | `external_process` through `docker` | provider capability and availability checked before dispatch |
| `research-parser-mineru` | `external_process` through `docker` | provider capability and availability checked before dispatch |
| Docker network, credential, and sidecar needs | Network deny is declared; network allowlists and secret handles are unsupported | no production MCP/sidecar profile is registered; request is denied rather than falling back to host execution |

The registry publishes `newsroom.execution-capability-denials/v1` stable denial codes. Docker currently declares unsupported network allowlists, CPU limits, generic resource limits, child-process allowlists, and secret-handle injection. The profile catalog and these denial flags are asserted by focused composition/API tests; they are contract evidence only, not target-deployment qualification.

## Composition Capability Matrix

| Capability | Required production port/provider | Status | Evidence reference | Owner / next action |
| --- | --- | --- | --- | --- |
| Runtime composition manifest | versioned manifest with checksum/fingerprints | contract-pass | current commit and focused composition/API tests | obtain startup evidence for every production process |
| Execution environment | admitted provider and execution receipt store | contract-pass / blocked | adapter tests pass; Research composition declares `docker` role-required and reports `available=false` | qualify real provider and immutable receipt |
| External process cancellation | termination receipt/reconciliation | contract-pass / blocked | existing provider contract tests; no live process receipt | add target-environment termination evidence |
| Child supervision | durable lease/receipt/transcript repositories | pending | caller inventory records Research `SubAgentRuntime` as blocked | route production child dispatch through `ChildAgentSupervisor` |
| Durable runtime event | event store/outbox and projection checkpoint | contract-pass / pending | Research composition binds canonical publisher and checkpoint reader; no external signature | complete durable event qualification |
| Operator read | authorizer and scoped cursor | pending | API readiness exposes composition diagnostics only | wire authenticated operator read service |
| Approval decision | Harness authorizer, receipt, outbox | pending | outside this implementation slice | prove write/read separation |
| Docker network/filesystem limits | provider capability profile | blocked | Docker daemon unavailable at baseline | qualify target deployment |
| Secret/credential handle | approved provider capability | blocked | no provider evidence | define provider or retain typed denial |
| Independent release/rollback signature | external governance chain | blocked | durable event qualification incomplete | obtain real signature chain |

The composition builder reports the following Docker capability profile on the authoring host: filesystem roots, network deny, isolated environment, argv policy, process-tree control, memory/process limits, and termination confirmation are declared; provider availability is `false`, and resource/secret capability flags remain unsupported. These declarations are contract data, not live deployment proof.

## Test and Deployment Ledger

| Date | Commit | Environment | Command or deployment action | Result class | Result | Receipt/event refs | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-08-26 | `0ed5ee0b` | authoring host | focused contract suites from prior safety change | contract-pass | existing contract coverage; not production qualification | see predecessor evidence | Docker daemon unavailable |
| 2026-08-26 | `c5b9f44b` | local `.venv` | `pytest tests/framework/agent/loop tests/framework/tool/runtime tests/framework/harness/runtime/test_tool_result_adapter.py -q` | contract-pass | execution environment injected into runner, batch, Harness, and composition `ToolExecutor` paths | test assertions only | no external provider |
| 2026-08-26 | `54e2ee82` | local `.venv` | `pytest tests/business/research/document/test_source_format_and_pdf.py tests/infrastructure/research/test_document_execution_adapter.py -q` | contract-pass | parser adapter maps identity, roots, env, argv, profile, and typed unavailable outcome | test assertions only | Docker daemon unavailable |
| 2026-08-26 | `a268a0df` | local `.venv` | `pytest tests/interfaces/api/test_runtime_execution_composition_api.py tests/interfaces/api -q` | contract-pass | readiness exposes manifest fingerprint and returns typed drift failure | API response assertions | no deployment observer |
| 2026-08-26 | `b77842c3` | local `.venv` | `openspec validate harness-runtime-production-composition --strict` | contract-pass | OpenSpec schema and task references validate | - | task progress remains partial |
| 2026-08-26 | `6bbf3eed` | local `.venv` | `pytest tests/framework/execution_environment/test_capability_admission.py tests/framework/execution_environment/test_runtime_composition.py tests/interfaces/api/test_runtime_execution_composition_api.py -q` | contract-pass | 15 passed; profile catalog and Docker unsupported-capability contract asserted | test assertions only | 8 FastAPI lifecycle deprecation warnings; no target provider |
| 2026-08-26 | `9cf2a46d` | local `.venv` | `pytest tests/framework/execution_environment/test_runtime_composition.py tests/interfaces/api/test_runtime_execution_composition_api.py tests/interfaces/services/test_diagnostic_application_service.py -q` | contract-pass | provider readiness, manifest drift, and diagnostic error mapping pass | test assertions only | Docker daemon unavailable; no target provider |
| 2026-08-26 | `9cf2a46d` | local `.venv` | `pytest tests/framework/tool/runtime tests/framework/execution_environment tests/interfaces/api/test_runtime_execution_composition_api.py tests/interfaces/services/test_diagnostic_application_service.py -q` | contract-pass | 95 passed, 2 skipped; typed profile, Graph identity, policy, provider, manifest, and required-port diagnostics pass | test assertions only | no external provider; FastAPI lifecycle deprecation warnings |
| 2026-08-26 | `9cf2a46d` | local `.venv` | `.\.venv\Scripts\python.exe -m scripts.dev smoke` | contract-pass | 2340 passed, 23 deselected; compile, Harness/Research/API/service/architecture coverage, AgentLoop smoke, and source validation passed | `sha256:471394a0bb870fd0fe5c242b48f34631dd70a8890e6f708514fb977358167cef` | 22 FastAPI lifecycle deprecation warnings; no Docker qualification |
| 2026-08-26 | `9cf2a46d` | local | `openspec validate harness-runtime-production-composition --strict`; `openspec validate --all --strict` | contract-pass | target change valid; 538 repository changes/specs passed, 0 failed | - | validation only; no external deployment signature |

Result class is one of: `contract-pass`, `integration-pass`, `skip`, `blocked`, `qualification-complete`.

## Crash-Recovery Matrix

| Boundary | Required recovery action | Test reference | Status |
| --- | --- | --- | --- |
| `PREPARED` before dispatch | dispatch once with original intent key | pending | pending |
| `DISPATCHED` without receipt | reconcile or mark indeterminate; never blind retry | pending | pending |
| `RECEIPT_COMMITTED` without event | replay outbox only | pending | pending |
| event publication duplicate | idempotent receipt/projection apply | pending | pending |
| child lease after parent restart | classify from durable lease/heartbeat/receipt | pending | pending |
| cancellation without termination proof | indeterminate/quarantine | pending | pending |

## External Qualification Blockers

- Durable event and Graph production release signatures remain external evidence; local keys, fake stores, or test deployments cannot close this blocker.
- Docker-backed execution requires a target environment with a reachable daemon and validated capability profile.
- Child cross-process recovery requires verified durable backing repositories, access scope, retention owner, encryption/locking decisions, and restart evidence.
- `business/research/document/pdf_compiler.py` no longer creates a host process; the legacy Nougat parser requires an injected execution adapter and remains inventory-classified `blocked` with follow-up required until a production profile is wired.
- Research dynamic child dispatch still constructs `SubAgentRuntime`; outbound MCP execution and the remaining worker/CLI composition roots require later wiring changes before the manifest can be claimed process-wide.
