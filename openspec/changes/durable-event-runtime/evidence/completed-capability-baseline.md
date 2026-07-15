# Completed Capability Baseline

This evidence freezes the completed capabilities directly modified or
superseded by `durable-event-runtime` without editing their history in place.
It was captured at HEAD `f21acc861562d2dbfa0a70a40665044ecb88408c`.

Several completed changes are ignored by the repository's broad `openspec/`
ignore rule and have not been promoted into `openspec/specs`. Their paths and
hashes are therefore recorded here as the durable review baseline. The source
directories are read-only for this change.

## Event-store baseline

| Capability source | SHA-256 of source spec | Frozen behavior | Relationship to this change |
| --- | --- | --- | --- |
| `openspec/changes/local-event-store/specs/local-event-store/spec.md` | `080bf0c851cd837a453e97ff0ac200fd4bda9069a498727d2e73c4ffafbb8a12` | Flat storage `EventRecord`, per-run JSONL append/read, inclusive 0-based line offset | Legacy import/export/read adapter; local production source becomes transactional SQLite |
| `openspec/changes/postgres-event-store/specs/postgres-event-store/spec.md` | `a753cbbf605f42cf21b091571b25b7868ff45c853c611e077604d792ae8d98f8` | `workflow_events`, run-local offset, DSN composition, post-run JSONL indexing | Replaced by canonical PostgreSQL append, 1-based per-stream sequence, identity collision checks, and transactional outbox |

The corresponding proposal, design, and task files are part of the frozen
baseline. `legacy_event_offset`, canonical `stream_sequence`, and consumer
checkpoint frontier are distinct concepts. Future archival of these completed
changes requires explicit modified/removed deltas; it must not reintroduce a
JSONL writer or line-offset authority.

## Workflow storage indexing baseline

| Source | SHA-256 / status | Frozen behavior |
| --- | --- | --- |
| `openspec/changes/archive/2026-07-14-workflow-storage-indexing/` | archived historical change | Valid runs write `events.jsonl`, then the event store contains matching records |
| `openspec/changes/archive/2026-07-14-artifact-runtime-boundary-hardening/specs/workflow-storage-indexing/spec.md` | archived safety delta | Path and integrity constraints around the legacy indexing path |
| `openspec/specs/workflow-storage-indexing/spec.md` | `603bf03238e73aac7f2a2d61f1eb6f45f5de500829d3cf5f5073610a6d5c8e58` | Current main specification before this change; still describes JSONL-before-index direction |

The current change's `workflow-storage-indexing` delta is the only place to
edit this behavior during apply. It reverses authority to durable append before
subscriber visibility, then redacted ordered JSONL projection with watermark
and checksum. The archived sources and current main specification are not
modified directly.

## Checkpoint and replay baseline

| Capability source | SHA-256 of source spec | Frozen behavior / compatibility requirement |
| --- | --- | --- |
| `openspec/changes/local-checkpoint-store/specs/local-checkpoint-store/spec.md` | `fc760f43b13d8cd4d02a2fb0342465d382d7524f599f6151f5c10ff60ded3f43` | Local JSON checkpoint and legacy event offset |
| `openspec/changes/workflow-checkpoint-creation/specs/workflow-checkpoint-creation/spec.md` | `4016c6c0f21af6ad21b477fbea8270b861901946f9691f1686ed2b9f046e1b57` | Save a completed-step checkpoint and emit `checkpoint_created` after save |
| `openspec/changes/workflow-runtime-p1-resume-recovery/specs/workflow-runtime-target-closure/spec.md` | `f78f98ab88022d7df72d649505b06bb99943111a6776d137186138f0fc1b723e` | Runner/approval/worker resume and post-resume manifest/event/replay integrity |
| `openspec/specs/harness-runtime/spec.md` | `b969d9a8d8bf05000e7fab61941a83df9947556fd87c178ad39d09f7e8843681` | Harness decisions and phase/worker/gate/budget state are durable and replay does not invoke an LLM |
| `openspec/changes/archive/2026-05-14-workflow-version-replay-artifacts/` | archived historical change | Versioned artifact replay contract; not a substitute for deterministic event-history replay |

The new contract preserves resume, approval, and strict inspection behavior
while replacing new checkpoint identity with `last_stream_sequence` and
`last_event_id`. A 0-based legacy offset remains explicit import metadata and
is never silently treated as a 1-based sequence.

## Run-event interface baseline

| Completed capability source | SHA-256 of source spec | Frozen compatibility surface |
| --- | --- | --- |
| `openspec/changes/run-inspection-interface/specs/run-inspection-interface/spec.md` | `5b69aaa408655393786be55e2c8d4f888110e5ad64fa6cba35b926bd10e592f6` | Application-service list/show boundary |
| `openspec/changes/mcp-run-events/specs/mcp-run-events/spec.md` | `6ebaff6ab5e8d8ac6f4bb24dcd60ccca1348de6c2576d35ac2a8667aae0107ee` | `news.run.events`, run-event resource, manifest JSONL parsing, response redaction |
| `openspec/changes/run-events-api/specs/run-events-api/spec.md` | `59577bf20b2e2f42726f6c84c59b9c102155cfa3bf5c8f3365b1471c7e18639c` | Public envelope, event count, limit, and invalid-request error |
| `openspec/changes/run-events-cli/specs/run-events-cli/spec.md` | `9a0e2d8f483f75947647451758fd869128c5d6e44f41ab60da158e26f63d25e4` | Service-backed JSON/text output, limit, and invalid exit status |
| `openspec/changes/mcp-run-inspection/specs/mcp-run-inspection/spec.md` | `f03107e89752c2d6bb736ee9e5812e8d877fa59c386baa7952296f57e25eb58b` | MCP uses `RunInspectionService` and validates safe run identifiers |

The reader source changes from JSONL to the application-owned durable reader.
Core API/CLI/MCP response fields and filters remain compatible. Stable
sequence pagination, high watermark, projection status, and unavailable/stale
metadata are additive. Any response or error-contract change discovered during
implementation requires an explicit delta in this change rather than an
implicit code-only change.

Artifact-integrity replay interfaces remain independently authoritative:

| Current main spec | SHA-256 |
| --- | --- |
| `openspec/specs/run-replay-cli/spec.md` | `718b205731987853b194ef11ebf255512e93311e622adc583f769564bf9db309` |
| `openspec/specs/run-replay-api/spec.md` | `6b8a50c572d2e9afbeaceb17b6c6014eb6b48e2dc4e952019b0b7121248b2c71` |
| `openspec/specs/mcp-run-replay/spec.md` | `3fe3fbfb019d65d9465f4340c6114af96ce19bfee569baf255a51e45fcb80add` |

Deterministic event replay adds state rebuild/history verification/redelivery;
it does not weaken or conflate the existing read-only artifact replay and
integrity contracts.

## Read-only historical paths

The following are immutable inputs for this apply:

- `openspec/changes/archive/2026-07-14-workflow-storage-indexing/**`
- `openspec/changes/archive/2026-07-14-artifact-runtime-boundary-hardening/**`
- `openspec/changes/archive/2026-06-05-harness-research-runtime/**`
- `openspec/changes/archive/2026-05-14-workflow-version-replay-artifacts/**`
- archived 2026-07-14 run replay changes
- completed but unarchived `local-event-store`, `postgres-event-store`,
  `local-checkpoint-store`, `workflow-checkpoint-creation`,
  `workflow-runtime-p1-resume-recovery`, `run-inspection-interface`,
  `run-events-api`, `run-events-cli`, `mcp-run-events`, and
  `mcp-run-inspection` change directories
- current main `workflow-storage-indexing`, `harness-runtime`, and run-replay
  specifications until OpenSpec archival merges this change's deltas

## Baseline decision

This change keeps the externally useful read, resume, inspection, and artifact
integrity contracts. It adapts their implementation to one canonical durable
event source and explicitly supersedes line-offset ordering, post-run JSONL
indexing, memory-only Harness event authority, and concrete-store access from
interfaces. Completed change history is not edited in place.
