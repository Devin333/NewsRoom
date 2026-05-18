# NewsRoom

NewsRoom is a spec-driven news intelligence runtime. The daily workflow runs through the shared Runner path, writes replayable artifacts, and keeps product `live` runs separate from deterministic development smoke runs.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

For macOS or Linux:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

## Install Modes

Use the mode that matches what you want to do:

```powershell
python -m pip install -e .
```

- Core runtime only.
- Suitable when you do not need local tests, vector memory, or extra service integrations.

```powershell
python -m pip install -e ".[qdrant]"
```

- Enables vector/memory features backed by `qdrant-client`.
- Use this when you need memory search, memory bootstrap, or memory reindex commands.

```powershell
python -m pip install -e ".[dev]"
```

- Full local development environment.
- Includes `pytest`, `qdrant-client`, API/runtime extras, and the tooling used by the documented smoke and test commands.

## Dependency Troubleshooting

If you see `ModuleNotFoundError` for `pydantic`, `pytest`, or `qdrant_client`:

1. Verify you are using the project virtual environment:

```powershell
python -c "import sys; print(sys.executable)"
```

It should point to `F:\github\NewsRoom\.venv\Scripts\python.exe` on Windows.

2. Reinstall the intended dependency set:

```powershell
python -m pip install -e ".[dev]"
```

3. Optional dependency note:
- Non-memory commands should work without `qdrant-client`.
- Memory/vector commands require `.[qdrant]` or `.[dev]`.


## Fixed Smoke Commands

These commands are the stable no-network/no-secret baseline:

```bash
python -m scripts.dev smoke
```

The aggregate smoke runs the fixed command set below:

```bash
python -m compileall -q core domain evidence interfaces quality sources storage workflows scripts
python -m interfaces.cli.news dev run-test-no-llm --topic "AI agents"
python -m interfaces.cli.news dev run-test-agent-loop --topic "AI agents"
python -m interfaces.cli.news run daily --profile live-offline --topic "AI agents" --source-limit 2
python -m interfaces.cli.news sources validate
```

Artifacts are written under `.newsroom/runs`.

## Live Smoke

The gated live smoke uses real configured RSS/Atom sources and a real OpenAI-compatible LLM:

```bash
python -m scripts.dev smoke-live
```

It exits successfully with `skipped` when live credentials or required config are not ready. To fail instead of skip:

```bash
python -m interfaces.cli.news dev run-live-smoke --topic "AI agents" --source-limit 3 --fail-if-unready
```

## Standard Commands

```bash
python -m scripts.dev compile
python -m scripts.dev test
python -m scripts.dev test-workflows
python -m scripts.dev test-services
python -m scripts.dev test-interfaces
python -m scripts.dev interface-smoke
python -m scripts.dev smoke
python -m scripts.dev smoke-live-offline
python -m scripts.dev smoke-live
python -m scripts.dev diagnose
```

GNU Make users can run the same command set through:

```bash
make install
make test
make smoke
make smoke-live
make diagnose
```

## Profiles

`live` is the product path: real sources, real LLM, real artifacts, and local JSON persistence by default.

`test-no-llm`, `test-agent-loop`, and `live-offline` are development and regression profiles. They are useful for CI and local checks, but they are not the product MVP path.

## Interface Layer

The interface layer exposes CLI, HTTP API, Web Console, and MCP entrypoints over application services. Start with:

```text
docs/09-INTERFACES_CLI_API_MCP.md
docs/api/README.md
docs/api/openapi.json
docs/web-console.md
docs/mcp.md
```

Useful local commands:

```bash
news reports latest --format markdown
news runs list --json
news mcp catalog --json
python -m scripts.dev export-openapi
python -m scripts.dev web-check
```

Example clients live under:

```text
examples/api/
examples/mcp/
```
