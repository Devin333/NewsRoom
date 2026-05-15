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

Create local environment settings:

```powershell
Copy-Item .env.example .env
```

Set `DASHSCOPE_API_KEY` in `.env` before running the real `live` profile. Leave `NEWS_DATABASE_DSN` empty to use the MVP local JSON repository and filesystem artifacts.

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
