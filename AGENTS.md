# NewsRoom Codex Instructions

This repository is the NewsRoom spec-driven news intelligence runtime.

## Project workflow

- Prefer OpenSpec for planned changes. The project keeps OpenSpec state under `openspec/`.
- Use the local Codex skills in `.codex/skills/` for OpenSpec workflows:
  - `$openspec-explore` for investigation and requirements exploration.
  - `$openspec-propose` to create a new OpenSpec change.
  - `$openspec-apply-change` to implement tasks from an existing change.
  - `$openspec-archive-change` to archive a completed change.
- Validate OpenSpec changes with `openspec validate <change> --strict` when a change is involved.

## Engineering guardrails

- Keep changes minimal and focused on the requested task.
- Preserve the main runtime path: source collection -> evidence -> agent analysis -> report -> quality gate -> artifacts/storage.
- Do not route deterministic work through agents when a normal function or service is enough.
- Interface layers should call application services rather than reaching into executors or stores directly.
- MCP server inbound interface and ToolRuntime outbound MCP adapters are separate concerns.

## Local checks

Common no-network checks:

```powershell
python -m scripts.dev compile
python -m scripts.dev test
python -m scripts.dev smoke
openspec list --json
```
