## Why

CLI and HTTP API can already inspect run artifacts, but MCP clients cannot read an artifact resource directly. Interface-layer architecture calls out artifact access as an MCP resource capability, and operators need the same artifact detail through the agent-facing surface without bypassing the artifact inspection service.

## What Changes

- Add an MCP artifact resource template for run artifact reads.
- Route artifact resource reads through `ArtifactInspectionService`.
- Cover the path with real local artifact tests and smoke commands.

## Out Of Scope

- Artifact mutation or deletion.
- Exposing raw filesystem paths outside the existing artifact detail contract.
- Adding new persistence tables.
