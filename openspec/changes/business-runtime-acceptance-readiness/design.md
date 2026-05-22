## Context

The previous change productized primary business boards with workflow runners, artifacts, subscriptions, feedback, improvements, evals, cross-board intelligence, and weekly trend outputs. This change adds a small acceptance/readiness layer that exercises those paths as a user-facing smoke and service contract.

## Goals / Non-Goals

**Goals:**
- Verify primary board runs, artifacts, subscription payloads, skill trace metadata, feedback/improvement traces, cross-board aggregation, weekly enhanced outputs, eval suite, and proposal persistence.
- Expose acceptance through an interface service and CLI command.
- Keep all behavior offline and deterministic.

**Non-Goals:**
- No framework/runtime refactor.
- No board runner/service rewrite.
- No new MCP tool or API router.
- No real delivery, notification, network, LLM, or automatic proposal application.

## Decisions

- Acceptance checks are simple dataclasses under `interfaces/models` so CLI and tests can serialize without depending on framework internals.
- `BusinessAcceptanceService` uses productized board runners and existing cross-board/weekly/eval services, but hides those details from CLI.
- Weekly acceptance uses an offline daily runner fixture path rather than live storage or external reports.
- Subscription productized payload consumption is added to the existing `SubscriptionApplicationService` as delivery-plan construction only.
- `LocalJsonImprovementProposalStore` keeps existing directory behavior and also accepts explicit `.json` file paths.

## Risks / Trade-offs

- CLI smoke commands can be slower because they run real offline workflows. Mitigation: use fixture signals and small source limits.
- Acceptance service writes artifacts by default under `.newsroom/acceptance`. Tests use `tmp_path`.
- Docs/OpenSpec paths are ignored by local git config, so implementation must use forced add only when committing.
