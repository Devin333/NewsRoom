## Context

`ResearchRetriever` returns a large metadata dictionary with policy name, enabled channels, counts, and degradations. PRD 16 needs this to evolve toward `RetrievalTrace` and policy config hash reporting so future channel extraction and YAML policy migration can be verified.

## Goals / Non-Goals

**Goals:**

- Add structured trace metadata without removing existing metadata keys.
- Compute a deterministic hash from the active `RetrievalPolicy` values.
- Keep current named policy builders and values unchanged.

**Non-Goals:**

- Do not move policy values to YAML in this slice.
- Do not refactor all retrieval stages into `RetrievalPipeline` yet.
- Do not change scoring or retrieval output ordering.

## Decisions

- **Hash current dataclass config:** Serialize the active policy dataclass into sorted JSON and hash it. This gives immediate version binding before YAML is introduced.
- **Trace as metadata bridge:** Add `retrieval_trace` to result metadata while preserving `retrieval_degradations` for compatibility.
- **Typed degradation helper:** Replace ad hoc degradation dict creation with `RetrievalDegradation` while keeping JSON output shape stable.

## Risks / Trade-offs

- **Policy hash changes when dataclass fields change** -> That is intended and makes policy drift observable.
- **Trace is still assembled inside `ResearchRetriever`** -> Later pipeline extraction can move the same trace object out without changing report shape.
