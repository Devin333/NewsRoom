## Context

The live answer eval slice added `--live-answer-eval` and an ask-callable conversion seam, but the default builder still reaches back into `PaperRagApplicationService` from the business layer. The violation is present both when using real production stores and when using `--papers-dir` fixture chunks.

## Goals / Non-Goals

**Goals:**
- Keep `business/research` free of `interfaces` imports.
- Preserve the live answer sample conversion path and `answer_eval_mode=live` metadata.
- Support fixture-backed live answer eval from parsed paper chunks without production stores.
- Make unsupported no-fixture live eval fail with a clear message instead of importing interface services.

**Non-Goals:**
- Do not implement scheduled nightly workflow wiring in this fix.
- Do not restore missing interface docs in this fix.
- Do not redesign `PaperRagApplicationService` or move production interface assembly in this fix.

## Decisions

- Build live answer eval around a business-owned ask callable.
  - The callable runs `PaperRAGSession` directly for fixture chunks, then converts the session result into the same payload shape consumed by `_live_answer_sample`.
  - This preserves testability and avoids an interface service wrapper solely to call `rag_ask`.
- Require chunks for the default business CLI live answer path.
  - Without `--papers-dir`, `business/research` cannot assemble production stores without crossing into infrastructure or interface ownership.
  - Future interface or script entrypoints may inject a production ask callable from an outer layer.
- Keep payload conversion local and narrow.
  - The CLI only emits the fields needed by answer evaluation: answer text, candidate details, citations, passages, gate results, decision, generation mode, status, and transcript id.

## Risks / Trade-offs

- `--live-answer-eval` without `--papers-dir` changes from implicit production service use to a clear error. This is intentional to protect layer ownership until an outer-layer entrypoint injects production assembly.
- The fixture path still depends on configured LLM credentials when the real answer worker runs. Existing live mode semantics already had that risk; PR tests continue to use fake callables.
