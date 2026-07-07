## Why

The enterprise RAG review notes that `RetrievalPolicy` has stable hashing and trace metadata, but policy values are still code-only. Operators can select one of the baked-in policy names with `NEWS_PAPER_RAG_POLICY`, yet they cannot bind a production run to a versioned YAML policy file without editing code.

## What Changes

- Add a typed retrieval policy config loader for YAML and JSON files.
- Add `NEWS_PAPER_RAG_POLICY_CONFIG` so production composition can load a policy file from the environment.
- Allow config files to choose a base named policy and apply validated overrides.
- Preserve existing named policy behavior when no config file is provided.
- Add tests for YAML loading, env wiring, validation failures, and policy hash changes.

## Capabilities

### New Capabilities

- `retrieval-policy-yaml-config`: Research RAG retrieval policies can be loaded from versioned YAML/JSON configuration files.

## Impact

- Affected Research RAG retrieval policy code: `business/research/rag/retrieval/policies.py`.
- Affected policy config helpers: `business/research/rag/retrieval/policy_config.py`.
- Affected tests: retrieval policy and policy config tests.
- No retrieval scoring behavior changes unless `NEWS_PAPER_RAG_POLICY_CONFIG` is set.
