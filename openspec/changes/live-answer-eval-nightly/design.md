## Context

`run_evidence_eval --deterministic-answer-eval` builds answer samples by concatenating gold facts or abstain text. This is useful for CI stability, but it should be identified as a deterministic pipeline check. The real gated answer path is available through `PaperRagApplicationService.rag_ask(generate=True)`, but direct use would read production stores and ignore `--papers-dir` fixture chunks.

## Goals / Non-Goals

**Goals:**
- Add a live answer eval mode that converts gated answer payloads into `EvidenceAnswerSample` rows.
- Reuse loaded golden pairs and expected behavior taxonomy.
- Preserve deterministic PR gate behavior and thresholds.
- Make report metadata/check labels explicit about deterministic versus live modes.

**Non-Goals:**
- Do not require external LLM calls in regular PR tests.
- Do not replace retrieval metrics or promotion thresholds in this slice.
- Do not implement scheduled workflow wiring; this change provides the CLI/reporting capability used by nightly jobs.

## Decisions

- Implement live answer sample construction as a helper that accepts an ask callable.
  - Rationale: production can pass the real service, while tests can pass a fake gated response without external APIs.
  - Alternative considered: instantiate `PaperRagApplicationService` directly in all cases. That would make tests and `--papers-dir` fixture usage depend on production storage.
- Record `answer_eval_mode` as `none`, `deterministic`, or `live`.
  - Rationale: downstream reports and promotion checks can distinguish pipeline self-checks from generated-answer evaluation.
- Disallow combining deterministic and live answer modes.
  - Rationale: a single evidence report should have one answer metric source.

## Risks / Trade-offs

- Live mode can be slow or flaky when backed by an external LLM. Mitigation: it is opt-in and intended for nightly/non-PR workflows.
- Fake-service tests do not prove model quality. Mitigation: they verify conversion, metadata, and failure taxonomy; production quality is measured when nightly runs with real answer workers.
