# Runtime Production Composition Evidence

## Evidence Status

This file is the qualification ledger for `harness-runtime-production-composition`. The current snapshot records implementation evidence and explicit blockers; it is not a production qualification sign-off. An entry is not production evidence until it contains the exact commit, command, environment capability, result classification, and immutable receipt/event reference required below.

## Baseline Snapshot

| Field | Value |
| --- | --- |
| Baseline date | 2026-08-26 |
| Baseline commit | `0ed5ee0b` |
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
| Current commit | `b77842c3` |
| Research composition manifest | `research-runtime`, version `1` |
| Composition fingerprint | `sha256:5a1d25bf2e483072f0b6790d6069094a19d121714298d8411d7c7072d5d51200` |
| Policy fingerprint | `sha256:9cb9fc09e1aea7f1e1f86f041d46e95c1669c83a787f4da5d79ffed25b1e39d9` |
| Provider fingerprint | `sha256:ec5b242b5643d44470cff3dff6f4851bf173537c1f54926adf871b56aaa4a3e5` |
| Registered execution profiles | `research-parser-marker`, `research-parser-mineru` (`external_process`) |
| Registered provider | `docker` |
| Production vertical slice | Research parser -> `ResearchParserExecutionAdapter` -> `ExecutionEnvironmentRegistry` -> Docker provider |
| API readiness behavior | optional composition verifies manifest integrity and returns typed `503` on drift/unavailable diagnostics |
| Qualification state | implementation evidence only; no real Docker receipt/event or external release signature |

## Composition Capability Matrix

| Capability | Required production port/provider | Status | Evidence reference | Owner / next action |
| --- | --- | --- | --- | --- |
| Runtime composition manifest | versioned manifest with checksum/fingerprints | contract-pass | current commit and focused composition/API tests | obtain startup evidence for every production process |
| Execution environment | admitted provider and execution receipt store | contract-pass / blocked | adapter tests pass; Docker capability reports `available=false` | qualify real provider and immutable receipt |
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
- `business/research/document/pdf_compiler.py` still contains a direct Nougat `subprocess.run` path; it is inventory-classified `blocked` with follow-up required and is not counted as migrated by this change.
- Research dynamic child dispatch still constructs `SubAgentRuntime`; outbound MCP execution and the remaining worker/CLI composition roots require later wiring changes before the manifest can be claimed process-wide.
