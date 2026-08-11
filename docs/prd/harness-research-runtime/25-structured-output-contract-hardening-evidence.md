# Stage 25 Structured Output Contract Hardening Evidence Ledger

> Status: VERIFIED
>
> Verification date: 2026-08-11
>
> PRD: `25-structured-output-contract-hardening.md`

## Delivery record

| Change | Commit | OpenSpec archive |
| --- | --- | --- |
| Local contract and deterministic gate | `0dab6195` | `2026-08-11-structured-output-contract-local-gate` |
| Provider capability routing | `615e5fbf` | `2026-08-11-structured-output-provider-capability-routing` |
| Harness and cache convergence | `0bef7907` | `2026-08-11-structured-output-harness-cache-convergence` |
| Provider evaluation and release | current delivery | `2026-08-11-structured-output-provider-evaluation-release` |

The prerequisite Research context artifact correction is independently recorded
in `88b3c089`; it is not counted as a Stage 25 feature change.

## Functional requirements

| Requirement | Implementation | Test evidence | Event / replay evidence | Rollout / rollback proof |
| --- | --- | --- | --- | --- |
| `FR-SO-001` Schema preflight | `framework/llm/structured_output/preflight.py`, `contracts.py` | `test_schema_preflight_fails_closed`, `test_client_preflight_rejects_schema_before_transport` | `structured_output_contract_compiled`, `structured_output_schema_preflight_failed` | Canonical local gate is mandatory; Change 1 archive |
| `FR-SO-002` Canonical local validation | `framework/llm/structured_output/validator.py` using `Draft202012Validator` | local ref, composition, numeric equality, and `additionalProperties` cases in `test_structured_output_contract.py` | `structured_output_local_validation_failed`, accepted terminal event | Local validation remains enabled for every provider rollout and rollback |
| `FR-SO-003` Strict JSON object decoding | `framework/llm/structured_output/decoder.py` and managed client terminal path | non-finite, duplicate-key, root, size, and depth cases; Research non-standard number case | `structured_output_decode_rejected` | Strict decoder is outside provider enforcement flags and cannot be rolled back |
| `FR-SO-004` Pydantic typed validation | typed adapter retained by `preflight.py`, invoked by `validator.py` | nested model, OpenAI normalization, cross-field and bounded diagnostic tests | `structured_output_typed_validation_failed` | Typed adapter identity is part of the contract/cache boundary |
| `FR-SO-005` Provider capability negotiation | `projection.py`, `routing/router.py`, `clients/config.py` | native, constrained, JSON-object local gate, fallback reprojection, and pre-transport reject tests | projection selected/rejected events carry provider, deployment, mode, revision | Enabled release required; DashScope release remains held/disabled |
| `FR-SO-006` Projection integrity | `ProviderSchemaProjection` coverage and digest in `projection.py` | stable projection, no canonical mutation, omission disclosure, unsupported limit tests | projection event includes projection and release identity | Shadow cannot enforce; rollback changes provider mode only |
| `FR-SO-007` Complete/stream parity | `openai_compatible.py`, `models/stream.py`, router terminal validation | complete/stream parity, interrupted stream, invalid terminal, cached replay tests | only verified stream terminal emits accepted metadata | No rollout flag permits provisional fragments to become verified |
| `FR-SO-008` Cache integrity | `cache/key.py`, `entry.py`, `runtime.py`, managed request identity | contract isolation, corruption revalidation, unmanaged ineligibility, stream terminal cache tests | `structured_output_cache_validation` | Cache can be disabled independently; local validation remains mandatory |
| `FR-SO-009` Deterministic repair | `framework/agent/loop/judge.py`, `loop.py`, `structured_output/managed.py` | unchanged-failure halt and one-repair-then-accept tests | repair requested, accepted, and budget exhausted events in durable trace | Harness budgets own retry/replan/halt; provider retry is not used |
| `FR-SO-010` Diagnostic contract | bounded `StructuredOutputDiagnostic` plus `observability.py` allowlists | bounded/redacted validation, typed error, event envelope, low-cardinality metric tests | stable code, validator, paths, digest, and bounded issue count | Raw payload and schema text are excluded from events and metric labels |
| `FR-SO-011` Durable replay | `framework/agent/loop/events.py`, `models/trace.py`, structured observability projection | repair/halt trace tests and full recorded Research transport integration | contract, projection, release, attempt, diagnostic summary, response fingerprint | Release and rollout revisions are included in projection records |
| `FR-SO-012` Architecture closure | managed boundary in `structured_output/managed.py` and migrated Research worker | `test_production_has_no_unmanaged_structured_output_parser_or_validator` | unmanaged requests are not cache eligible or accepted | Architecture test prevents reintroduction of bypasses |
| `FR-SO-013` Security/resource bounds | preflight schema limits, strict decoder instance limits, local-ref-only policy | invalid ref, unknown keyword, schema limit, response size/depth, redaction tests | preflight/decode rejection uses bounded diagnostics | Remote refs and resource-limit failures always fail closed |
| `FR-SO-014` Evaluation gate | `evaluation.py`, `release.py`, `scripts/structured_output_eval.py` | independent gates, anti-compensation, tamper, full-corpus coverage, approval, shadow, scope, config tests | report/release/corpus/observation digests are replayable identities | recorded reference approved; real DashScope deployment held and disabled |

## Acceptance criteria

| Acceptance criterion | Implementation and test proof | Event proof | Rollout proof |
| --- | --- | --- | --- |
| `AC-SO-001` Invalid schema fails before call | preflight compiler plus parameterized invalid-schema and transport-call-count tests | `structured_output_schema_preflight_failed` | no bypass flag; local preflight is mandatory |
| `AC-SO-002` Non-standard JSON cannot pass | strict decoder, generic client, cache, and Research candidate tests reject non-finite and duplicate-key input | decode rejection; no accepted/cache event | strict decoder is retained on every rollback path |
| `AC-SO-003` Draft semantics are correct | `Draft202012Validator` tests cover `1.0`, boolean/number inequality, `uniqueItems`, `oneOf`, local refs, and extras | local validation failure diagnostics | versioned corpus pins semantic coverage |
| `AC-SO-004` Nested Pydantic closes | typed adapter tests cover nested refs, inner required/type, cross-field failure, and value redaction | typed validation failure event | typed adapter revision participates in contract identity |
| `AC-SO-005` Provider projection is honest | provider routing suite covers coverage, omitted keywords, fallback reprojection, release scope, and pre-transport reject | projection selected/rejected includes digest, coverage, release and rollout | native/constrained require approved enabled evidence; shadow stays local |
| `AC-SO-006` Complete/stream agree | parity test asserts identical validated object and contract/projection identity; interruption tests reject fragments | only terminal validation can emit accepted | streaming capability and release must both be eligible |
| `AC-SO-007` Repair is bounded | transport remains single-attempt; Harness repair succeeds once or halts on repeated fingerprint/budget exhaustion | repair requested and budget exhausted phase events | budgets are Harness configuration, not model output |
| `AC-SO-008` Cache is schema-isolated | key binds contract identity; read/write validation and corruption tests fail closed | cache validation event records hit/miss/reject without payload | cache disable does not disable local gate |
| `AC-SO-009` Domain gate remains independent | Research evidence mismatch tests and publication gate tests reject schema-valid unsupported candidates | Research gate/transcript records the domain failure after structure acceptance | provider release evaluation separately gates grounding/citation/quality |
| `AC-SO-010` Production call surface is closed | architecture inventory test plus full recorded production composition test | all accepted paths emit managed contract/projection metadata | architecture test is a permanent regression gate |

## Evaluation and verification

The committed recorded-provider reference evaluation replays all eight corpus
schemas across ten observations, including four held-out Research observations.
Its independent results are:

| Metric | Result |
| --- | ---: |
| schema validity | `1.0` |
| first-pass validity | `0.9` |
| repair success | `1.0` |
| answer quality | `0.905` |
| evidence grounding | `0.935` |
| citation completeness | `0.9625` |
| provider rejection | `0.0` |
| latency p95 | `1490 ms` |
| average tokens | `474.1` |
| average cost | `$0.00132` |

Verification commands and outcomes:

- focused changed-surface suite: `118 passed`;
- `python -m scripts.dev compile`: passed;
- `python -m scripts.dev smoke`: `2049 passed, 23 deselected`, source validation
  `is_valid=true`, `error_count=0`, `warning_count=0`;
- `openspec validate structured-output-provider-evaluation-release --strict`:
  passed before archive;
- `openspec validate --all --strict`: `522 passed, 0 failed` after archive;
- `git diff --check`: passed.

FastAPI lifespan deprecation warnings remain pre-existing and are outside this
PRD. No live-provider evidence was collected, so the DashScope native mode is
explicitly not production-approved.
