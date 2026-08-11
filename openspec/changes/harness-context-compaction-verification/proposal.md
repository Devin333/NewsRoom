## Why

The current Harness context path labels compression as verified after halving summary strings and token estimates, without a typed plan, tool-transaction integrity, evidence-loss proof, a second budget gate, or a durable source/result snapshot relationship. Now that router-managed model admission is deterministic, Harness needs a production semantic compaction boundary that can either prove the transformed context is structurally valid, evidence-safe, within budget, and replayable, or fail closed before any provider call.

## What Changes

- Replace segment-local string truncation with immutable typed context groups, protection reasons, tool-transaction state, and deterministic group validation.
- Add versioned `ContextCompactionPolicy`, `ContextCompactionPlan`, allowlisted actions, explicit action/summary/replan bounds, and stable plan identity.
- Implement reversible actions first: deduplication, durable-reference replacement, authorized tool-set reduction, and extractive evidence-span selection. No action may silently rewrite protected groups.
- Introduce a structured `ContextSummaryCandidate` port for optional LLM-generated candidates; candidates never self-promote and must carry covered groups, source refs, claim support, omissions, unresolved questions, tool outcomes, and a loss-risk declaration.
- Replace unconditional `context_compression_verified` emission with deterministic structure, protection, provenance, evidence/loss, action-budget, and post-compaction context-budget gates.
- Persist immutable source/result snapshots and a versioned compaction record that binds plan, actions, before/after counts, retained/removed/replaced groups, summary refs, gate evidence, policy/model/tokenizer revisions, and a stable reason code.
- Project compaction facts through the canonical Harness transcript/event owner and extend replay readers to verify checksums and reconstruct decisions without invoking an LLM or re-running side effects.
- **BREAKING**: remove production behavior that fabricates summary artifact URIs, halves token estimates without recounting, or records verified compression before all deterministic gates pass.

## Capabilities

### New Capabilities

- `harness-context-grouping`: Typed semantic groups, protected-content policy, message order, and tool-call/result transaction integrity.
- `harness-context-compaction-planning`: Deterministic bounded plans, allowlisted actions, execution ordering, and fail-closed pressure outcomes.
- `harness-context-summary-verification`: Structured summary candidates plus deterministic source, evidence, loss, structure, and budget verification.
- `harness-context-compaction-replay`: Versioned records, source/result snapshots, canonical durable event projections, integrity validation, and side-effect-free replay.

### Modified Capabilities

- `harness-runtime`: Strengthen context assembly so transformed context can be returned or dispatched only after deterministic post-compaction VERIFY and durable evidence commit.

## Impact

- Primary code: `framework/harness/context`, `framework/harness/runtime/context_replay.py`, canonical Harness transcript/event projections, and Research context composition adapters.
- Existing `ContextEnvelope`, `ContextSnapshot`, and `CompressionRecord` serialized forms require a versioned migration path; legacy records remain readable as unverified evidence but cannot authorize provider dispatch.
- LLM/provider code remains outside semantic ownership. Optional summary generation is an injected worker port; Harness alone validates and promotes a result snapshot.
- Tests expand across context models/planning/gates, tool transactions, evidence provenance, post-compaction recount, replay corruption, bounded failure, and Research integration.
