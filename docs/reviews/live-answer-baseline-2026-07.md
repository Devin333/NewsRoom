# Paper RAG Live Answer Baseline Readiness - 2026-07-07

## Status

No real LLM baseline was produced in this local run because the required LLM configuration is not present in the current environment.

This is an external configuration gap, not a missing local corpus or command path:

- `data/eval/golden_set.json` exists.
- Golden set size: 79 pairs.
- Expected behavior distribution: 67 `answer`, 12 `abstain`.
- Distinct paper ids in the golden set: 20.
- `.newsroom/papers` exists locally.
- Parsed paper artifacts available locally: 76 `research_document.json` files.
- Required local LLM environment variables were absent: `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`.

## Verified Command Path

The real-corpus live answer eval command is wired through `python -m scripts.dev run-live-answer-eval` and should be run once LLM credentials are configured:

```powershell
$env:OPENAI_BASE_URL = "<provider base url>"
$env:OPENAI_API_KEY = "<secret>"
$env:OPENAI_MODEL = "<model id>"
python -m scripts.dev run-live-answer-eval `
  --golden-set data/eval/golden_set.json `
  --papers-dir .newsroom/papers `
  --output-dir .newsroom/eval/live-answer-real
```

Expected output artifacts:

- `.newsroom/eval/live-answer-real/result.json`
- `.newsroom/eval/live-answer-real/evidence/evidence_regression_report.json`
- `.newsroom/eval/live-answer-real/evidence/evidence_regression_report.md`

The report must include real `answer.abstention_accuracy`, `answer.success_rate`, and failure taxonomy counts before this baseline can be treated as a production-readiness data point.

## GitHub Actions Path

The scheduled workflow `.github/workflows/rag-live-answer-eval.yml` already has:

- weekly cron and `workflow_dispatch`
- fixture live answer eval
- real-corpus live answer eval when `.newsroom/papers` exists
- skip behavior when `OPENAI_BASE_URL` or `OPENAI_API_KEY` is missing
- artifact upload for `.newsroom/eval/live-answer` and `.newsroom/eval/live-answer-real`

To produce the first official baseline:

1. Configure repository secrets: `OPENAI_BASE_URL`, `OPENAI_API_KEY`, and optionally `OPENAI_MODEL`.
2. Ensure the workflow environment provides `.newsroom/papers` or restore parsed paper artifacts before the real-corpus step.
3. Manually dispatch `RAG Live Answer Eval`.
4. Download the `rag-live-answer-eval` artifact.
5. Copy the real-corpus metrics and failure taxonomy into this document.

## Local Readiness Snapshot

Commands used for this snapshot:

```powershell
Test-Path -LiteralPath .newsroom\papers
Get-ChildItem -LiteralPath .newsroom\papers -Recurse -Filter research_document.json -File
python - <<'PY'
import json
from collections import Counter
from pathlib import Path
payload = json.loads(Path("data/eval/golden_set.json").read_text(encoding="utf-8"))
print(len(payload))
print(dict(Counter(item.get("expected_behavior", "answer") for item in payload)))
print(len({item.get("paper_id") for item in payload}))
PY
```

Current conclusion: corpus and command path are ready, but the first real LLM baseline remains pending until credentials and an Actions/manual run are available.
