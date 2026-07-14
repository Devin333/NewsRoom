## Why

`03-TOOL_RUNTIME_TARGET_ARCHITECTURE.md` lists `artifact.search` as a retrieval
tool. Current built-in artifact tools can write and load exact paths, but agents
cannot discover run artifacts through Tool Runtime.

## What Changes

- Add built-in `artifact.search`.
- Search only within the current run artifact directory.
- Support optional path prefix, query substring, and max result limit.
- Return artifact refs and lightweight match metadata without loading full
  content into the prompt.

## Out Of Scope

- Cross-run artifact search.
- Vector search or semantic search.
- Binary file indexing.
