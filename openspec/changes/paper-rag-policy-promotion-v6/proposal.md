# Paper RAG Policy Promotion V6

## Why

V1-V5 improved blind semantic Paper RAG retrieval, but the tuned behavior still lives behind a mix of policy name, CLI switches, and benchmark output. A new retrieval strategy should not be treated as production-ready because one test run looks good. It needs an explicit policy name, a repeatable promotion checklist, and report artifacts that prove train/dev/test separation, gold quality, retrieval observability, answer quality, and failure reasons.

## What Changes

- Add an explicit `paper_blind_semantic_rag_v1` retrieval policy while preserving the default policy.
- Make the blind semantic policy opt in to the deterministic lightweight field reranker without requiring a second CLI flag.
- Add a policy promotion checklist to benchmark suite JSON/Markdown artifacts.
- Write a standalone `policy_promotion_checklist.json` and `.md` artifact in benchmark output directories.
- Gate promotion readiness on the PRD thresholds and on required report sections being present.

## Out Of Scope

- Promoting the new policy as the default runtime policy.
- Training a neural reranker or changing embedding providers.
- Removing historical benchmark artifacts or prior completed OpenSpec changes.
