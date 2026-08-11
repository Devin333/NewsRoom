# Structured-output provider evaluation

This directory contains versioned evidence used by the deterministic Harness
gate before a provider-native structured-output mode can be selected.

## Evidence layout

- `corpora/provider-schema-corpus-v1.json` is a NewsRoom-authored schema corpus.
  Its taxonomy is informed by JSONSchemaBench, but it copies no upstream rows.
- `evaluations/recorded-reference-native-v1.json` is a deterministic recorded-
  transport observation set with capability and held-out Research cases.
- `releases/recorded-reference-native-v1.json` is an approved reference release.
  It proves the release workflow, not the behavior of any external provider.
- `releases/dashscope-deepseek-v4-flash-held-v1.json` keeps the current
  DashScope deployment held and disabled until live-provider evidence passes.

The upstream revisions and license disposition are pinned in the corpus asset.
Neither upstream schema corpus is vendored into this repository.

## Reproduce the gate

Run from the repository root:

```powershell
.\.venv\Scripts\python.exe -m scripts.structured_output_eval `
  --schema-corpus configs/llm/structured_output/corpora/provider-schema-corpus-v1.json `
  --observations configs/llm/structured_output/evaluations/recorded-reference-native-v1.json `
  --release-record configs/llm/structured_output/releases/recorded-reference-native-v1.json `
  --output .artifacts/structured-output/recorded-reference-native-v1-report.json
```

Exit code `0` means every independent threshold passed and the release record
matches the evaluated provider, deployment, capability, corpus, observations,
baseline, projection mode, and report digest. A failed quality, grounding,
citation, schema, rejection, latency, token, or cost gate cannot be compensated
by another metric.

## Promotion and rollback

1. Capture a versioned observation set from the exact provider deployment and
   capability revision. Mark external-provider evidence as `live_provider`.
2. Replay it through the canonical compiler, decoder, and local validator with
   the command above. Keep the report as immutable release evidence.
3. Build an approved release record from the passing report. The Harness owns
   the decision; an LLM response cannot approve or modify the record.
4. Start with `rollout_state: shadow`. Shadow records expose diagnostics only;
   requests continue through `json_object_local_gate` or fail closed.
5. Change to `enabled` only after the shadow comparison passes, then bind the
   exact `release_id` and `record_digest` in the deployment capability.
6. On any rollback trigger, publish a new immutable record that selects the
   declared fallback. Never edit an already approved record in place.

The runtime rejects native or constrained provider enforcement when the release
is missing, digest-mismatched, held, revoked, out of scope, or not enabled.
