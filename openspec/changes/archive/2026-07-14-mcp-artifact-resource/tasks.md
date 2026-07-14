## 1. OpenSpec Setup

- [x] 1.1 Create `mcp-artifact-resource` OpenSpec change.
- [x] 1.2 Define proposal, design, tasks, and spec delta.
- [x] 1.3 Keep OpenSpec files, local state, generated files, and secrets out of commits.

## 2. MCP Artifact Resource

- [x] 2.1 Add artifact service factory to MCP application service.
- [x] 2.2 Add artifact resource template to MCP catalog.
- [x] 2.3 Route `news://runs/{run_id}/artifacts/{artifact_key}` reads through `ArtifactInspectionService`.
- [x] 2.4 Add focused tests using real local artifact files.
- [x] 2.5 Run real smoke, tests, OpenSpec validation, secret scan, and commit.
