# Design

## Shape

`framework.harness.rag.metrics` owns a small immutable `RAGSessionMetrics` value object and a builder function that derives counters from the authoritative run state:

- final session status and decision type
- transcript event count
- final budget snapshot
- accepted/rejected/conflicting evidence counts
- context pack and answer presence
- answer attempts and supplemental round counts
- gate failure counters grouped by gate name
- rejection counters grouped by rejection reason

The builder is deterministic and does not perform IO.

## Service Surface

`PaperRagApplicationService` keeps its existing `metrics` key but now merges session metrics into the gated response. Existing high-level fields such as `context_pack_id`, `accepted_evidence_count`, and `decision_type` remain available for compatibility.

## Boundaries

Metrics are derived from the Harness session state and transcript events. The service layer only forwards them; it does not re-derive gate or budget counters.
