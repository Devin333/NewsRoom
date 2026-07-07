## Context

The current real-corpus live answer baseline passes configured answer thresholds, but `answer_failure_details.jsonl` still shows many answerable questions abstaining because the retrieved context lacks the primary or interpretation evidence. A large slice of those questions are not generic method questions. They ask about evaluation choices, experiment sections, appendix details, benchmark contamination, user-study findings, dataset splits, prompt comparisons, and win-rate judgment setup.

Today those questions often hit the fallback `concept_method` rule because they contain broad words such as "what", "which", "approach", or "text", but do not contain the narrower numerical-result phrases. The fallback route applies `section_role_filter=["method"]` and `recall_routes=("method_body",)`, which under-fetches result paragraphs, tables, captions, and conclusion/analysis context.

## Goals / Non-Goals

**Goals:**
- Route evaluation/result-oriented live-answer questions to `numerical_result` or `comparison` when their wording clearly asks for experimental/result context.
- Keep explicit table, figure, formula, and citation routing precedence intact.
- Add tests grounded in actual failure questions rather than invented keyword-only examples.

**Non-Goals:**
- Do not weaken live answer thresholds.
- Do not change the answer gate or abstention marker behavior.
- Do not introduce LLM-based routing or agent-driven workflow decisions.
- Do not tune retrieval weights without evidence from the routing failure slice.

## Decisions

- Keep the kernel classifier generic and unchanged. The rule matcher already supports caller-owned rule ordering; this repair belongs in Paper-specific signal lists and route semantics.
- Add result/evaluation signals before the `concept_method` fallback. This preserves rule-order behavior while giving live-answer evaluation questions access to result/table/conclusion routes.
- Add comparison signals for prompt/comparison wording that asks about compared conditions or experimental comparisons.
- Keep explicit `table_query` and `formula_query` ahead of result signals so concrete element references still route to the specialized retrievers.

## Risks / Trade-offs

- Broad result terms such as "results" can over-route some conceptual summaries to result context. This is acceptable for the live failure slice because result-aware routes still include paragraph candidates and propositions, while the method-only route demonstrably under-fetches evidence.
- Adding many phrases can make rules harder to scan. Mitigate by grouping signals around observed live-answer categories and by pinning representative questions in tests.
