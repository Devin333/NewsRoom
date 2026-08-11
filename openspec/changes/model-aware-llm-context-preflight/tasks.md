## 1. Context Profile and Preparation Models

- [x] 1.1 Implement immutable `ModelContextProfile` with strict identity, limit, revision, fraction, output-default, safety-margin, fallback-counter, and provider-auto-truncation validation.
- [x] 1.2 Implement `EffectiveContextBudget`, typed admission statuses/results, and immutable `PreparedLLMRequest` projections with redacted `to_dict()` evidence.
- [x] 1.3 Implement canonical prepared-request fingerprinting that covers provider-semantic response-affecting fields and excludes diagnostic metadata and secrets.
- [x] 1.4 Export the new preflight contracts from `framework.llm.context` and `framework.llm` without changing legacy guard semantics.

## 2. Provider-Semantic Normalization and Token Counting

- [x] 2.1 Define provider request-normalizer and token-counter ports plus registries keyed by provider/tokenizer family and version.
- [x] 2.2 Implement component-level `LLMTokenCount` validation for messages, tools, response schema/format, media, protocol overhead, method, and revisions.
- [x] 2.3 Implement the explicitly labeled canonical UTF-8-byte conservative fallback and fail closed when the profile forbids fallback and no counter is registered.
- [ ] 2.4 Extract a pure OpenAI-compatible payload normalizer shared by preflight and provider dispatch, covering model, messages, tools, response format/output schema, max output, temperature, and media-bearing message payloads.
- [x] 2.5 Implement the request preparer that resolves output reserve, computes the effective input budget, counts the normalized payload, produces the fingerprint, and returns a typed admission without mutating semantic context.

## 3. Deployment Configuration and Provider Overflow

- [x] 3.1 Add strict versioned context-profile configuration parsing, allowed-key validation, and migration from complete existing capability window/output values.
- [x] 3.2 Bind parsed profiles to `ModelDeployment` and reject mismatched deployment/provider/model identity before routing.
- [ ] 3.3 Switch `OpenAICompatibleClient.complete()` and `.stream()` to the shared payload normalizer with golden tests proving wire payload parity.
- [ ] 3.4 Add `LLMProviderContextOverflow`, map HTTP 413 and explicitly supported structured provider overflow codes, preserve bounded numeric diagnostics, and prohibit internal retry/sleep.

## 4. Router Complete Admission

- [ ] 4.1 Inject the request preparer into `LLMRouter` and run profile resolution, normalization, count, and admission for every enabled capability-compatible deployment before provider/global-budget admission.
- [ ] 4.2 Implement typed profile/input/output/counter capacity rejection and deterministic configured fallback without provider calls, cooldown changes, or budget reservations for rejected deployments.
- [ ] 4.3 Dispatch only the admitted normalized request and reserve/settle global budget using the admitted total input count instead of the legacy rough estimate.
- [ ] 4.4 Emit redacted profile/prepared/admission/capacity-fallback events and attach the admitted prepared projection to response metadata and route manifests.
- [ ] 4.5 Implement bounded provider-overflow recovery to at most one different eligible deployment, with no same-deployment redispatch or cooldown mutation.

## 5. Router Stream Admission

- [ ] 5.1 Add router `stream()` / route-resolution entrypoints that reuse the complete-path preparation, deployment ordering, budget, event, and manifest contracts.
- [ ] 5.2 Preserve incremental normalized provider events and prohibit fallback after any user-visible stream event has been yielded.
- [ ] 5.3 Reserve admitted input budget before opening the provider iterator and settle normalized stream usage without attributing rejected deployments.
- [ ] 5.4 Apply the single bounded overflow fallback only before visible stream output and prove that partial streams are never spliced.

## 6. Tests and Architecture Evidence

- [x] 6.1 Add unit tests for profile validation, exact boundary/one-token overflow, output-default/output-limit conflicts, component sums, counter selection, forbidden fallback, stable fingerprints, and semantic non-mutation.
- [x] 6.2 Add config and OpenAI payload golden tests for tools, response schema/format, model override, multilingual/media-shaped messages, revisions, and unknown/invalid profile fields.
- [ ] 6.3 Add router complete adversarial tests for missing profiles, oversized input, oversized output request, tool-schema-only overflow, capacity fallback, all-deployments rejection, redacted evidence, and admitted global-budget counts.
- [ ] 6.4 Add router stream tests for complete/stream preparation parity, no iterator open on rejection, incremental delivery, no fallback after visible output, and usage accounting.
- [ ] 6.5 Add provider overflow tests for HTTP 413, mapped structured HTTP 400 codes, unmapped message text, no internal retry/sleep, bounded cross-deployment recovery, and redacted drift evidence.
- [ ] 6.6 Add an architecture assertion that router admission no longer calls `estimate_request_tokens` and document that direct-client callsite convergence remains outside this change.

## 7. Validation and Delivery

- [ ] 7.1 Run focused LLM context, models, config, provider-client, routing, budget, stream, and cache-contract tests and fix root causes.
- [ ] 7.2 Run `python -m scripts.dev compile` and the broad non-live test suite appropriate to shared LLM/router changes.
- [ ] 7.3 Run `python -m scripts.dev smoke` and verify the context/router smoke path uses an admitted deployment profile.
- [ ] 7.4 Run `openspec validate model-aware-llm-context-preflight --strict` and re-run relevant validation for the active cache change if shared router contracts were touched.
- [ ] 7.5 Audit staged files, redaction, dependency direction, and the live dirty-worktree baseline; update PRD/OpenSpec evidence without claiming repository-wide callsite closure.
- [ ] 7.6 Commit only this change's verified files with path-scoped staging, leaving unrelated user modifications untouched.
