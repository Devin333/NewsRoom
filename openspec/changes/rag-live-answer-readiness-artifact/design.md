## Context

The workflow currently emits a skip message when `OPENAI_BASE_URL` or `OPENAI_API_KEY` is missing and only uploads artifacts when those secrets are present. That means skipped scheduled runs leave no downloadable readiness artifact. Local inspection also showed the parsed corpus and curated golden set are available, but LLM configuration is absent.

## Goals / Non-Goals

**Goals:**
- Produce `.newsroom/eval/live-answer-readiness/readiness.json` and `.md` for every workflow run.
- Include secret presence booleans and lengths never secret values.
- Include golden set pair count, expected behavior distribution, distinct paper count, papers directory presence, and `research_document.json` count.
- Make fixture and real-corpus run eligibility explicit.
- Keep the helper deterministic and no-network.

**Non-Goals:**
- Configure secrets.
- Run an LLM call.
- Generate parsed paper artifacts.
- Treat readiness as a substitute for a successful live baseline.

## Decisions

1. Implement readiness under `business/research/rag/evaluation`.
   - Rationale: the logic is evaluation-specific and should be testable without GitHub Actions.
   - Alternative: inline shell in the workflow. Rejected because shell-only readiness is harder to unit test and maintain.

2. Expose a CLI and `scripts.dev` command.
   - Rationale: the workflow and local operators should use the same readiness path.

3. Upload readiness artifacts regardless of LLM secret presence.
   - Rationale: skipped runs are the most important case for diagnosis.

## Risks / Trade-offs

- [Risk] Readiness artifacts could be mistaken for live baseline metrics. -> Mitigation: the Markdown states that readiness is not a production baseline and distinguishes eligibility from actual evaluation results.
- [Risk] Secret handling can leak values. -> Mitigation: only boolean presence and optional configured model id are recorded; API keys are never printed.
