## Context

The deterministic CI eval gate creates a small fixture corpus and golden set, then runs retrieval and answer metric checks without an external model. Live answer eval should reuse that fixture corpus shape but call the gated Harness answer path with configured LLM credentials during scheduled/manual runs.

## Goals / Non-Goals

**Goals:**
- Provide a stable `python -m scripts.dev run-live-answer-eval` entrypoint.
- Generate live answer evidence artifacts under `.newsroom/eval/live-answer` by default.
- Keep the GitHub workflow opt-in and secret-aware.
- Contract-test workflow command, secret references, and artifact upload.

**Non-Goals:**
- Do not run live LLM evaluation during PR CI by default.
- Do not alter deterministic PR promotion gates.
- Do not implement model-quality remediation from the live report in this slice.

## Decisions

- Add a business-owned `run_live_answer_eval` helper that invokes `run_evidence_eval` with fixture papers, a generated golden set, live retrieval, and live answer eval.
  - Rationale: this keeps command behavior testable while reusing existing evidence report output.
- Reuse the CI eval fixture paper writer through a public wrapper.
  - Rationale: live answer eval and deterministic CI eval should measure the same small controlled corpus unless a later change introduces a dedicated live corpus.
- Skip the GitHub live step when `OPENAI_BASE_URL` or `OPENAI_API_KEY` are missing.
  - Rationale: scheduled workflows should not fail just because secrets are not configured in a fork or developer copy.

## Risks / Trade-offs

- The workflow can pass without executing live answer eval if secrets are absent; the skip message is explicit and contract-tested.
- The live report can fail when model quality regresses or LLM access is down. That is the intended signal for scheduled/manual runs.
