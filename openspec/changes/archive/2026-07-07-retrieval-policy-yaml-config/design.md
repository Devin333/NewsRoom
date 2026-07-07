## Context

`RetrievalPolicy` is a dataclass used by the production paper RAG retriever, benchmark suite, and retrieval trace metadata. The previous `retrieval-policy-config-and-trace` change added deterministic config hashing but intentionally deferred YAML policy migration.

The production composition root already calls `build_retrieval_policy_from_env()`, so adding a config path environment variable there enables production policy configuration without changing interface or framework layers.

## Goals / Non-Goals

**Goals:**

- Load retrieval policy config from YAML and JSON files.
- Support `base_policy` plus validated `overrides`.
- Reject unknown fields and malformed root/override shapes before constructing a policy.
- Preserve `NEWS_PAPER_RAG_POLICY` named policy selection when no config file is set.
- Keep policy hashes derived from the effective dataclass values.

**Non-Goals:**

- Add remote config fetching or hot reload.
- Change default policy values.
- Change retrieval ranking, channel routing, or benchmark thresholds.
- Migrate every benchmark CLI argument to config files.

## Decisions

1. Use `NEWS_PAPER_RAG_POLICY_CONFIG` as the production config path.

   The existing `NEWS_PAPER_RAG_POLICY` remains the named base selector. If the file also declares `base_policy`, the file wins because it is the versioned artifact being loaded.

2. Keep config additive and explicit.

   Config files use:

   ```yaml
   base_policy: paper_hybrid_rrf_rag_v1
   overrides:
     name: enterprise_hybrid_v1
     overfetch_multiplier: 6
     sparse_search_limit_multiplier: 5
   ```

   Unknown override keys fail fast to avoid silent policy drift.

3. Reuse existing policy hash path.

   Once a config is materialized into `RetrievalPolicy`, `stable_policy_config()` and `policy_config_hash()` already produce deterministic metadata.

## Risks / Trade-offs

- Invalid production config can prevent startup. This is preferable to silently running an unintended retrieval policy.
- Deep schema validation is intentionally narrow and dataclass-driven. More advanced config evolution can add a formal schema later without changing callers.

## Migration Plan

1. Deploy with no `NEWS_PAPER_RAG_POLICY_CONFIG`; behavior is unchanged.
2. Add a versioned YAML file and point `NEWS_PAPER_RAG_POLICY_CONFIG` at it in a controlled environment.
3. Confirm retrieval metadata contains the configured policy `name` and a changed `retrieval_policy_config_hash`.
