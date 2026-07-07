## Context

The current CI workflow runs compile, workflow tests, service tests, PRD daily tests, and smoke checks, but it does not execute the Paper RAG evidence evaluator. The repository already has a real deterministic path for offline retrieval evaluation in `business.research.rag.cli.run_evidence_eval`: parsed `research_document.json` files are chunked, indexed into in-memory stores, retrieved by `ResearchRetriever`, scored by `EvidenceRetrievalEvaluator`, and written as `EvidenceRegressionReport` artifacts.

The enterprise RAG review asks for PR-level retrieval metrics plus promotion thresholds. A full benchmark suite is too heavy for normal PR CI because it includes train/dev/test splitting, optional LLM judges, spot-check flows, and larger corpus expectations. CI needs a smaller gate that still exercises the same evaluator and retrieval code paths.

## Goals / Non-Goals

**Goals:**
- Add a fast, no-network, deterministic Paper RAG eval gate for PR CI.
- Exercise real parsed-paper chunking, in-memory retrieval, evidence evaluation, policy metadata, and threshold checking.
- Write durable artifacts for evidence regression and promotion gate review.
- Fail with a non-zero exit code when any configured retrieval or promotion threshold fails.
- Keep the gate callable from both CI and local developer workflows through `scripts.dev`.

**Non-Goals:**
- Replace the full benchmark suite or nightly larger-corpus evaluation.
- Add Qdrant, Postgres, external LLM, visual model, or network dependencies to PR CI.
- Tune production retrieval thresholds from the mini corpus.
- Add answer-generation, human spot-check, or LLM judge promotion checks to the PR gate.

## Decisions

1. Add a dedicated CI gate module under `business/research/rag/evaluation/`.

   The gate is evaluation orchestration, not a service-layer behavior. Keeping it near the existing RAG evaluation modules lets it reuse the evaluator and benchmark promotion data structures without adding interface or infrastructure dependencies.

2. Generate a deterministic mini corpus at runtime.

   The gate writes a small parsed-paper fixture into its output directory and then calls the existing `run_evidence_eval` flow with `--papers-dir`, `--build-golden-set`, and `--live-retrieval`. This keeps CI self-contained while still validating the real chunker, golden builder, retriever, evaluator, report writer, and thresholds.

3. Use strict but PR-sized thresholds.

   CI thresholds are intentionally scoped to regression detection on the deterministic mini corpus: overall retrieval hit rate, evidence coverage, required evidence type coverage, source locator coverage, MRR, and by-QA-type visibility. These checks are not a production promotion decision for a large benchmark, but the artifact reports the relevant promotion-threshold posture.

4. Expose only one developer command.

   `python -m scripts.dev test-rag-eval-gate` becomes the stable local and CI entry point. The underlying CLI remains available for tests and direct debugging, but CI should not duplicate evaluator arguments in YAML.

## Risks / Trade-offs

- Mini corpus overfitting -> The gate is only a PR regression tripwire; larger benchmark promotion remains separate.
- Deterministic fixture drift -> The fixture is generated from code and covered by tests that assert expected reports and failure behavior.
- Private benchmark helpers becoming coupled -> The CI gate writes its own small promotion report instead of depending on private benchmark-suite markdown internals.
- CI duration growth -> The gate uses in-memory retrieval and a tiny corpus with no external services, keeping runtime close to targeted unit tests.

## Migration Plan

1. Land the gate disabled nowhere; it runs as part of CI immediately after existing service tests.
2. Developers can reproduce locally with `python -m scripts.dev test-rag-eval-gate`.
3. Roll back by removing the CI step or temporarily lowering only the CI gate command from the workflow while preserving the evaluator code.
