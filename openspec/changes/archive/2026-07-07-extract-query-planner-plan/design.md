## Context

`ResearchRetriever.retrieve()` currently performs query routing, filter construction, candidate-limit calculation, recall orchestration, reranking, context expansion, and metrics assembly in one method. Earlier PRD 16 slices introduced recall channel primitives and extracted individual recall channels, but the top-level retriever still owns route planning details such as formula sparse filters, element-label overfetch, citation overfetch, and route metadata.

## Goals / Non-Goals

**Goals:**

- Introduce a serializable `RetrievalPlan` that captures the current route, filters, candidate filters, candidate limit, element labels, and stage specs.
- Move query planning into `QueryPlanner` without changing existing policy values or ranking behavior.
- Keep `ResearchRetriever` execution compatible by consuming the plan while leaving recall/rerank/expand logic in place for later slices.
- Add focused tests for planner behavior so later pipeline extraction has a stable contract.

**Non-Goals:**

- Do not introduce the final `RetrievalPipeline` in this slice.
- Do not move rerank or context expansion into new modules yet.
- Do not change intent classification rules, overfetch multipliers, field weights, or any tuned scoring constants.
- Do not introduce YAML policy loading in this slice.

## Decisions

- **Plan DTOs are value objects:** `RetrievalPlan`, `ChannelSpec`, `FusionSpec`, `RerankSpec`, and `ExpanderSpec` are dataclasses with simple primitives and `to_dict()` helpers. This keeps the plan suitable for traces and future harness transcript storage.
- **Planner receives policy at construction:** candidate limit and formula sparse filter behavior depend on `RetrievalPolicy`, so `QueryPlanner(policy)` owns those decisions while `paper_policy.py` continues to own intent classification.
- **Request shape stays lightweight:** `QueryPlanner.build()` accepts the existing `RetrievalRequest` shape. It reads only `question` and `limit`, avoiding a dependency on chunk stores or recall channels.
- **Retriever migration is incremental:** `ResearchRetriever.retrieve()` uses `plan.route`, `plan.filters`, `plan.candidate_filters`, `plan.element_query_labels`, and `plan.candidate_limit`, but the execution body remains otherwise unchanged to preserve behavior.

## Risks / Trade-offs

- **Partial refactor still leaves the retriever large** -> This slice intentionally moves only query planning; pipeline, rerank, and expander extraction remain PRD 16 follow-up work.
- **Plan can drift from execution metadata** -> Tests assert planner outputs for key route types, and retriever metadata now reads from the plan where applicable.
- **Circular imports between planner and retriever** -> Planner accepts a structural request object via `Any`/attribute access and imports only policy/route helpers, not `ResearchRetriever`.
