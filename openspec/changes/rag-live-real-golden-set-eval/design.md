## Context

`run_evidence_eval` already supports `--golden-set`, `--papers-dir`, `--live-retrieval`, and `--live-answer-eval`. The higher-level live answer helper currently always prepares fixture papers and runs `--build-golden-set`, so callers cannot point the scheduled live path at `data/eval/golden_set.json` and a real parsed paper corpus.

## Goals / Non-Goals

**Goals:**
- Keep fixture mode as the default live answer smoke path.
- Add an explicit external-corpus mode using `golden_set_path` plus `papers_dir`.
- Ensure external-corpus mode does not call `write_ci_eval_fixture_papers()` or pass `--build-golden-set`.
- Record which mode ran in the result payload for artifacts and debugging.
- Let the GitHub workflow attempt the real-corpus mode when `.newsroom/papers` exists and skip clearly otherwise.

**Non-Goals:**
- Commit large parsed paper artifacts.
- Configure or verify repository secrets.
- Run a real LLM call from local tests.
- Refactor `run_evidence_eval` into a structured core API; that remains the P2-3 follow-up.

## Decisions

1. Add optional `golden_set_path` and `papers_dir` parameters to `run_live_answer_eval`.
   - Rationale: this matches the underlying evidence eval contract and keeps CLI/API naming obvious.
   - Alternative: merge real rows into the generated fixture golden set. Rejected because it hides the evaluated corpus and still ties real evaluation to fixture generation.

2. Require both external inputs together.
   - Rationale: live answer eval needs golden pairs and parsed paper chunks. A golden set without matching papers would fail later with a less helpful error.

3. Keep workflow real-corpus execution best-effort.
   - Rationale: `.newsroom/papers` is an environment artifact, not a tracked repository directory. The workflow should preserve fixture coverage and emit a clear skip when real artifacts are absent.

## Risks / Trade-offs

- [Risk] The repository golden set can reference paper ids not present in the provided papers directory. -> Mitigation: use the existing `run_evidence_eval --live-answer-eval` validation path and keep failure visible when the real-corpus step actually runs.
- [Risk] Workflow skip could be mistaken for real-corpus success. -> Mitigation: name the step explicitly and print a skip message when `.newsroom/papers` is missing.
