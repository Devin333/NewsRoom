# Design: Provider evaluation and release gate

## Decisions

### Versioned evidence, not provider declarations

NewsRoom-authored corpus cases carry immutable revisions, upstream taxonomy pins, content digests, and license disposition. JSONSchemaBench is used as a feature/complexity taxonomy; upstream dataset rows are not redistributed. Recorded observations identify their transport/evaluator provenance and are replayed through the canonical compiler, decoder, and local validator.

### Independent deterministic gates

The evaluator computes every required metric from case-level observations. Each threshold and regression check must pass independently. Schema-validity gains cannot compensate for lower answer quality, grounding, citation completeness, or exceeded latency/cost budgets.

### Harness owns approval

Only a passed evaluation report can produce an approved release record. The record is immutable and binds provider, deployment, capability revision, mode, corpus/baseline/report digests, workflow scopes, rollout revision, evidence refs, and rollback action. Projection consumes this record but cannot create or promote it.

### Shadow cannot enforce

`shadow` records expose the candidate capability and evaluation identity for comparison, but native strict/constrained projection remains ineligible. The actual call must use an independently eligible deployment or an explicitly authorized JSON-object local gate. `enabled` requires an approved, identity-matching release.

### Rollback preserves local truth

Rollback changes only provider enforcement: it selects a prior approved capability revision, JSON-object local gate, another deployment, or reject. Strict decoding, canonical local validation, typed validation, Harness repair limits, and durable events remain enforced.

## Corpus and evidence layout

- `configs/llm/structured_output/corpora/provider-schema-corpus-v1.json`
- `configs/llm/structured_output/evaluations/recorded-reference-native-v1.json`
- `configs/llm/structured_output/releases/*.json`

The versioned observation set contains both capability and held-out Research splits,
and every schema in the corpus must be observed. The committed approved reference
record is scoped to the recorded transport used by repeatable tests. The real
DashScope deployment remains held with a rollback-safe disabled record until a
live evaluation artifact is reviewed.

## Failure policy

- Missing, malformed, held, revoked, wrong-scope, or identity-mismatched release records make native/constrained enforcement ineligible before transport.
- An evaluation report with any failed gate cannot be promoted.
- Corpus/evaluation/release digest mismatch fails closed.
- Shadow mode cannot silently fall through to native enforcement.
