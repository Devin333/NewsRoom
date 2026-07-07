## Context

Readiness artifacts already summarize LLM configuration, golden set contents, parsed paper artifacts, and eligibility. The workflow needs to consume that same deterministic decision instead of duplicating a weaker shell-only directory check.

## Decisions

1. Add `--require-fixture` and `--require-real-corpus` to the readiness CLI.
   - Without these flags, the command remains diagnostic and returns `0`.
   - With a required eligibility flag, the command still writes artifacts and prints JSON, but returns `1` when the requested eligibility is false.

2. Gate only the real-corpus workflow step with `--require-real-corpus`.
   - The existing secret-level `if:` remains the outer guard.
   - The inner shell `if python -m scripts.dev check-live-answer-readiness --require-real-corpus` prevents misleading real-corpus metrics when corpus coverage is incomplete.

## Non-Goals

- Fetch or generate missing paper artifacts.
- Change golden set membership.
- Treat fixture readiness as proof of real-corpus baseline readiness.
