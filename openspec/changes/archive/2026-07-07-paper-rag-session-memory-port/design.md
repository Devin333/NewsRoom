## Context

`BoundedRAGSessionController` already supports `MemoryPort` and deterministic memory namespace gates. `ResearchRAGPolicyBuilder` also maps `ResearchRetrievalGoal.allowed_memory_namespaces` into `RAGSessionSpec.allowed_memory_namespaces`. The missing piece is the business/interface composition: `PaperRAGSession` never receives a memory port, and the production factory never builds one.

The existing `framework.memory.MemoryRuntime` returns typed `MemoryRecallResult` objects. Harness RAG memory recall expects lightweight dictionaries containing `namespace`, `memory_ref`, and relevance/score fields. An adapter is needed between those contracts.

## Goals / Non-Goals

**Goals:**

- Wire a `MemoryPort` into `PaperRAGSession`.
- Build a production memory port from `MemoryRuntime` and `VectorMemoryStoreAdapter` when explicitly enabled.
- Keep the first production slice recall-only and episodic by default.
- Preserve namespace filtering end-to-end.
- Add tests for adapter mapping, session injection, factory opt-in, and vector namespace persistence.

**Non-Goals:**

- Store reader repair memory in PostgreSQL.
- Add automatic RAG memory writes from normal paper ask runs.
- Enable memory recall by default.
- Change planner behavior or memory gate semantics.

## Decisions

1. Use `NEWS_RAG_MEMORY` as the opt-in switch.

   The default path remains unchanged until operators explicitly enable memory recall.

2. Use `MemoryRuntime` as the adapter source.

   This reuses the existing policy, recall strategy, trace, and store boundaries instead of creating another memory search path.

3. Default to episodic memory only.

   The first production connection targets `MemoryKind.EPISODIC`, with workflow/session/global scopes allowed by the existing workflow memory policy.

4. Do not implement writes in this slice.

   The adapter satisfies the `MemoryPort` protocol but keeps write methods non-mutating. Controlled memory writes and reader repair persistence remain separate changes.

## Risks / Trade-offs

- Enabling memory can surface low-quality existing memories. The harness memory relevance gate and namespace filtering reduce the blast radius, and the feature is opt-in.
- Vector memory namespace persistence changes stored payload shape additively. Existing records without namespace continue to load, but namespace-scoped recall will only include records with matching namespace.

## Migration Plan

1. Deploy with `NEWS_RAG_MEMORY` unset; behavior remains unchanged.
2. Ensure memory records are written with the intended namespace.
3. Enable `NEWS_RAG_MEMORY=1` and optionally set `NEWS_RAG_MEMORY_COLLECTION`.
4. Confirm RAG transcripts include memory recall results instead of `"memory port is not configured"`.
