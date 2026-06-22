# NewsRoom

NewsRoom is a spec-driven news intelligence runtime. The current backend product path is Harness + Research: Harness owns workflow control, deterministic gates, replayable traces, and artifact publication while Research owns paper analysis domain behavior.

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

```powershell
python -m pip install -e ".[ocr]"
```

- Enables the local Nougat CLI used by the PDF document parser.
- Prefer the Docker path below for repeatable Nougat installs, because the OCR stack pulls PyTorch and large model/runtime dependencies.

## Nougat OCR Docker

Build the Nougat OCR image:

```powershell
docker compose build nougat
```

Check the CLI:

```powershell
docker compose run --rm nougat --help
```

Convert a PDF into Nougat `.mmd` output:

```powershell
docker compose run --rm nougat path/to/file.pdf -o .newsroom/nougat
```

The first conversion downloads the configured Nougat model into the `nougat-cache` Docker volume. The Docker default is `0.1.0-base`; use a different model tag when needed:

```powershell
$env:NOUGAT_MODEL = "0.1.0-small"
docker compose run --rm nougat path/to/file.pdf -o .newsroom/nougat
```

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
python -m compileall -q framework business interfaces infrastructure scripts tests
python -m interfaces.cli.news api openapi --json
python -m interfaces.cli.news sources validate
python -m interfaces.cli.news mcp catalog --json
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

Research production runs use real sources, real model providers when configured, real artifacts, and local JSON persistence by default. Deterministic fake ports are used in tests only.

## Interface Layer

The interface layer exposes CLI, HTTP API, Web Console, and MCP entrypoints over application services. Start with:

```text
docs/09-INTERFACES_CLI_API_MCP.md
docs/api/README.md
docs/api/openapi.json
docs/sdk/python.md
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
examples/sdk/
examples/mcp/
```
