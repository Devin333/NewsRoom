# Change: Converge structured output with Harness and cache integrity

## Why

The canonical structured-output contract and provider projection are now deterministic, but downstream cache, AgentLoop, and Research paths still reconstruct parts of that contract independently. Cache identity includes raw schema data instead of an explicit compiled identity, AgentLoop reduces schema diagnostics to free-form text, and Research revalidates already-managed output at a business adapter boundary.

This change supersedes the output-judge portion of `agent-loop-p0-output-contract-artifacts`. The LLM remains a candidate worker; only Harness may authorize bounded repair, accept the candidate after deterministic domain/evidence gates, or halt when budget is exhausted.

## What Changes

- Bind cache keys and entries to canonical structured-output contract identity and revalidate every read and write through the compiled contract.
- Project stable structured-output diagnostics into AgentLoop verdicts, bounded repair attempts, metrics, and replay-safe events without raw output or schema bodies.
- Remove Research candidate-local schema interpretation and require managed verified output before domain/evidence validation.
- Add one redacted observability contract for contract compilation, provider projection, decode/validation failure, repair, cache validation, and acceptance.
- Add architecture tests that reject unmanaged production structured-output parsing and validation callsites.

## Impact

- Affected specs: `agent-loop-p0-output-contract-artifacts`, `llm-structured-output`
- Affected code: `framework/llm/cache`, `framework/llm/structured_output`, `framework/llm/routing`, `framework/agent/loop`, `framework/agent/models`, `infrastructure/research`, and focused tests
- Cache corruption and contract revision changes fail closed as misses; rejected outputs are never written.
- Structured-output repair consumes existing AgentLoop retry/iteration budgets and cannot trigger transport-level retry.
