# NewsRoom Codex Instructions

This repository is the NewsRoom spec-driven news intelligence runtime.

## Language and collaboration

- All user-facing replies, plans, questions, summaries, and status updates must be in Chinese.
- Questions to the user must be in Chinese. If options are offered, option labels and descriptions must also be in Chinese.
- Code, file paths, commands, API names, class names, function names, schemas, and identifiers should remain in English.
- When a task is large, a lead agent may coordinate multiple sub-agents in parallel, but the lead agent remains responsible for integration, verification, cleanup, and the final commit.

## Project workflow

- Prefer OpenSpec for planned changes. The project keeps OpenSpec state under `openspec/`.
- Use the local Codex skills in `.codex/skills/` for OpenSpec workflows:
  - `$openspec-explore` for investigation and requirements exploration.
  - `$openspec-propose` to create a new OpenSpec change.
  - `$openspec-apply-change` to implement tasks from an existing change.
  - `$openspec-archive-change` to archive a completed change.
- Validate OpenSpec changes with `openspec validate <change> --strict` when a change is involved.
- Commit after every completed code change. Before committing, run checks appropriate to the changed surface. If checks fail, fix the root cause before committing.

## Implementation standard

- Deliver final-quality implementations for the requested scope. Do not submit placeholder, temporary, demo-only, or "minimal pass" implementations.
- Keep changes focused on the requested scope, but do not confuse "focused" with incomplete. The result must be production-shaped for that scope.
- If code or tests fail, make a root-cause fix. Do not skip tests, weaken assertions, hard-code around failures, or preserve known-bad behavior for convenience.
- Place code where the ownership is clearest. Avoid high coupling, cross-layer shortcuts, duplicated abstractions, and business logic leaking into framework modules.
- Design for readability, extensibility, replaceability, and unit testing. Add abstractions only when they remove real complexity or establish a clear boundary.
- Production code must use real data sources, real business models, and real runtime paths. Do not fake business behavior in production code.
- Tests may use fake data, fake workers, fake repositories, fixtures, and in-memory stores to reduce development cost, but they must verify real business rules and architecture constraints.

## Architecture guardrails

- Preserve the intended runtime path unless a current OpenSpec change explicitly replaces it: source collection -> evidence -> agent analysis -> report -> quality gate -> artifacts/storage.
- Do not route deterministic work through agents when a normal function or service is enough.
- Interface layers should call application services rather than reaching into executors or stores directly.
- MCP server inbound interface and ToolRuntime outbound MCP adapters are separate concerns.
- Harness is the flow controller. LLMs are workers that generate candidate content only; they must not decide workflow routing, quality pass/fail, memory writes, tool authorization, or publication.
- Harness execution must follow a bounded PLAN -> EXECUTE -> VERIFY state machine. VERIFY must be performed by deterministic gates, failed gates must trigger controlled replan/retry/halt, and `max_replans`, `max_turns`, and retry budgets must prevent infinite loops.
- Every Harness phase transition must be recorded to a durable transcript or event log so runs can be replayed and reviewed.
- Skills may evolve only through Harness-controlled candidate, validation, evaluation, promotion, versioned release, and rollback workflows. LLMs may propose skill patches, but must never directly modify active skill packages, decide promotion, skip held-out evals, disable quality gates, or publish production skill versions.
- Business repair experiences, such as Research reader repair cases, must first be stored as memory and consolidated into procedural strategies before they can seed skill evolution; a normal business run must not directly update active skills.
- During the Harness + Research rebuild, `business/research` must not depend on legacy `business/boards/paper_radar`, `interfaces`, or `infrastructure`.
- Keep useful legacy framework assets; delete code and tests that no longer serve the new architecture. Do not keep compatibility layers unless explicitly required by the active OpenSpec change.

## Local checks

Common no-network checks:

```powershell
python -m scripts.dev compile
python -m scripts.dev test
python -m scripts.dev smoke
openspec list --json
```
