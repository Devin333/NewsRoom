## Why

NewsRoom currently estimates an abstract LLM request with `len(serialized) / 4`, records that estimate as router metadata, and then calls the selected deployment without checking its actual context window or the requested output reserve. This permits known-overflow requests to reach providers, leaves configured context strategies without runtime semantics, and prevents cache, streaming, budget, and replay layers from sharing one admitted request identity.

The first delivery slice of stage 24 must establish a deployment-aware physical preflight before Harness-owned semantic compaction can be made safe. Harness remains the semantic context owner; the LLM layer only normalizes the provider-semantic request, counts it, resolves an effective physical budget, and returns a deterministic admission result.

## What Changes

- Add immutable model context profiles, effective context budgets, component-level token counts, prepared request fingerprints, and typed admission outcomes.
- Add a provider/model token-counter port plus a conservative UTF-8-byte fallback whose method and revision are explicit in every result.
- Normalize all token-affecting request fields once so counting, provider dispatch, cache identity, complete, and stream can share the same prepared request contract.
- Resolve requested and reserved output tokens against deployment limits; reject unsupported output requests instead of silently clamping them.
- Make `LLMRouter` prepare and admit each capability-compatible deployment before any provider call, and select a configured fallback when the primary is physically too small.
- Add complete/stream parity for deployment-aware preflight, routing evidence, global budget reservation, and fallback behavior.
- Normalize provider context overflow as a non-transient capacity/profile-drift failure; never retry the same prepared payload as an ordinary transient error.
- Emit redacted router evidence containing profile, tokenizer, count breakdown, budget, admission reason, and prepared-request fingerprint without prompt or tool contents.
- **BREAKING**: router-managed production calls require a valid deployment context profile; deployments with no usable context window fail closed unless an explicitly configured conservative fallback profile is injected.
- Keep the old standalone `LLMContextGuard` API only as a migration surface. It no longer defines the router production admission contract, and its future-facing truncate/summarize strategy names do not authorize content mutation.

## Capabilities

### New Capabilities

- `llm-model-context-preflight`: Versioned model profiles, provider-semantic request preparation, component token counting, output reservation, fingerprints, and deterministic admission.
- `llm-routing-context-admission`: Router enforcement for complete and stream, capacity-aware deployment fallback, budget integration, redacted evidence, and fail-closed missing-profile behavior.
- `llm-provider-context-overflow`: Stable provider-overflow taxonomy, estimator-drift evidence, and bounded recovery rules that prohibit blind same-payload retry.

### Modified Capabilities

None. The completed but unarchived `llm-context-guard` change is a narrow estimate-and-signal MVP and has no canonical spec under `openspec/specs/`; this change introduces the production contract without pretending that an absent canonical requirement can be modified.

## Impact

- Affected framework paths: `framework/llm/context`, `framework/llm/models`, `framework/llm/routing`, and provider error normalization under `framework/llm/clients`.
- Deployment/model configuration gains versioned context-profile fields and strict numeric validation.
- `LLMRouter` gains a shared preparation path for complete and stream and records admitted prepared-request metadata in response/route manifests.
- `GlobalBudgetTracker` reserves the admitted input-token count rather than the legacy rough estimate.
- The active `llm-cache-production-hardening` change consumes the prepared fingerprint and deployment/profile revision but retains ownership of cache eligibility, lookup, storage, single-flight, and replay.
- Harness context selection, evidence protection, summary generation, compaction verification, memory, RAG, publication, and quality gates remain outside this change.
