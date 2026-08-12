## 1. U10 Contract Baseline

- [x] 1.1 Add executable parity fixtures for router, AgentLoop, and Workflow prompt reservation, actual settlement, replacement, cache, fallback, stream, failure, and resume paths.
- [x] 1.2 Add architecture and consumer-inventory tests that fail while Agent and Workflow own duplicate mutable `GlobalBudget*` implementations or canonical governance imports forbidden layers.
- [x] 1.3 Record every observed semantic difference in `evidence.md` as `merge`, `retain`, or `adapt` with its authoritative owner and golden expectation.

## 2. Canonical Contract And Ledger

- [x] 2.1 Add strict immutable dimension, amount, policy, scope, decision, reservation, settlement, view, snapshot, event, reason-code, and typed-error models under `framework/governance/budget`.
- [x] 2.2 Implement canonical decimal parsing/serialization, bounded integer validation, policy digesting, JSON-safe allowlisted projections, and unknown-field/version rejection.
- [x] 2.3 Implement root ledger scope registration, ancestor-effective limits, read-only preflight/view, and linearized atomic reservation with idempotent operation identity.
- [x] 2.4 Implement exactly-once settlement, proven-undispatched release, expiry, indeterminate handling, terminal idempotency, and invariant checks.
- [x] 2.5 Add contract/property-style tests for invalid values, boundaries, root/child inheritance, idempotency, reservation replacement, conflicting terminal delivery, and immutable views.

## 3. LLM Adapter And Router Cutover

- [x] 3.1 Add `LLMBudgetAdapter` for prepared input/output/cost reservation and normalized provider/cache/fallback/stream settlement metadata while retaining per-call policy and pricing in `framework/llm/budget`.
- [x] 3.2 Convert `framework.llm.budget.GlobalBudgetTracker` into a one-release compatibility facade over the canonical ledger without a second mutable usage or serialization algorithm.
- [x] 3.3 Migrate router complete, cache hit/miss, primary/fallback, provider error, and structured-output paths to explicit logical and dispatch operation identities.
- [x] 3.4 Migrate router stream paths so fragments never settle, one terminal settles exactly once, and lost terminal becomes indeterminate.
- [x] 3.5 Add LLM adapter/router conformance tests for logical versus physical call accounting, pricing/Decimal parity, duplicate delivery, and no provider call after denial.

## 4. Agent Workflow And Scope Migration

- [x] 4.1 Replace Agent runtime duplicate budget definitions with canonical/LLM facade exports and migrate AgentLoop direct-client and router-backed paths to consume exactly one settlement.
- [x] 4.2 Register subagent child scopes on the shared root ledger and prove local projections cannot bypass root capacity or expose sibling reservation history.
- [x] 4.3 Remove Workflow duplicate cumulative definitions while retaining Workflow-owned tool-call and wall-time accounting over a canonical LLM view.
- [x] 4.4 Migrate Workflow runner, outcome finalization, summaries, checkpoint, and resume to canonical snapshot/restore and remove all private `_usage` mutation.
- [x] 4.5 Add Agent/Workflow integration tests for shared identity, budget exhaustion projection, tool/wall-time owner retention, scope inheritance, and legacy snapshot decode.

## 5. Durable Events Recovery And Concurrency

- [x] 5.1 Register bounded redacted `newsroom.budget-event/v1` lifecycle schemas and add an adapter to the canonical event candidate/store owner.
- [x] 5.2 Implement versioned snapshot/restore, bounded terminal idempotency records, legacy flat-snapshot read migration, and strict invariant validation.
- [x] 5.3 Implement ordered offline replay with contiguous revisions, duplicate/conflict/gap detection, and no LLM/provider/cache/tool calls.
- [x] 5.4 Add barrier-based concurrent reservation tests at call/token/cost `limit-1`, `limit`, and `limit+1` boundaries across workflow and subagent scopes.
- [x] 5.5 Add crash-boundary tests around reserve, durable append, dispatch, provider return, settlement, and indeterminate reconciliation.
- [x] 5.6 Add security tests proving prompt, secret, tool payload, provider body, exception, and arbitrary metadata never enter snapshot/event/diagnostic payloads.

## 6. Harness And Compatibility Closure

- [x] 6.1 Wire canonical budget facts into Harness durable transcript input and deterministic controlled outcomes without adding routing authority to the ledger or LLM worker.
- [x] 6.2 Remove duplicate production imports/exports and enforce the one-release compatibility registry across repository imports, public exports, dynamic entries, checkpoint/replay, and persisted payload readers.
- [x] 6.3 Update documentation/index references and complete `evidence.md` with implemented paths, rollback contract, test commands, and results.

## 7. Verification And Commit

- [x] 7.1 Run `openspec validate framework-budget-contract-convergence --strict` and targeted governance/LLM/Agent/Workflow/event/checkpoint/replay suites.
- [x] 7.2 Run `python -m scripts.dev compile`, architecture tests, source validation where applicable, and `python -m scripts.dev smoke`; fix every root-cause failure.
- [x] 7.3 Run `git diff --check`, audit scoped status and ignored OpenSpec files, mark completed tasks/evidence, and create the required focused implementation commit.
