## Why

`03-TOOL_RUNTIME_TARGET_ARCHITECTURE.md` lists `artifact.load` and
`artifact.write` as core MVP-to-target tools. Current tests use ad hoc lambdas
for artifact behavior, so agents cannot register a real artifact tool set.

## What Changes

- Add built-in artifact tool registration.
- Implement `artifact.write` using `ArtifactManager.write_json/write_text`.
- Implement `artifact.load` using real run artifact files.
- Preserve ToolExecutor policy, validation, redaction, telemetry, and approval
  behavior.

## Out Of Scope

- Artifact search.
- Binary artifact IO.
- Cross-run artifact access.
