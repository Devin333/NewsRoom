## Context

P0-P2 established the BFF route pattern, reader payload, and PaperRadar/cache-backed public paper data. The reader page currently exposes a disabled Ask this paper panel. The PRD's Phase 3 asks for Reader Agent behavior, but full LLM-powered PDF extraction is larger than the next safe increment.

## Goals / Non-Goals

**Goals:**
- Provide a usable Ask this paper flow for one paper at a time.
- Ground answers in reader sections, summary fields, and evidence/source refs.
- Return citations with section/evidence identifiers so the UI can show why an answer was produced.
- Cache answers and keep agent failure non-blocking.

**Non-Goals:**
- No full PDF text extraction pipeline in this change.
- No cross-paper graph traversal beyond placeholders.
- No external LLM provider requirement; the first implementation uses deterministic section retrieval and extractive synthesis.
- No persistent user sessions or conversation history.

## Decisions

- Use deterministic extractive QA first. It is testable, offline, and avoids routing a new user-facing operation through an LLM before section extraction is mature.
- Model the response as `PaperReaderAnswer` with `answer`, `citations`, `confidence`, `cached`, and `generatedAt`. This can later be produced by an LLM without changing the frontend contract.
- Store an in-memory service cache keyed by paper id, locale, normalized question, and reader section hash. The cache is process-local and safe to drop.
- Add `POST /api/v1/papers/{paper_id}/ask` and BFF `POST /api/papers/[paperId]/ask`; browsers continue to use only BFF endpoints.
- Keep answers public-only by building from `PaperReaderPayload.to_dict()` fields and existing redaction helpers.

## Risks / Trade-offs

- Extractive answers can feel less intelligent than LLM answers -> UI labels the feature as grounded beta and shows citations/confidence.
- In-memory cache is not shared across workers -> acceptable for v1; the response contract includes `cached` for future persistent cache.
- Section quality is limited while PDF text extraction is lightweight -> answer falls back to abstract/summary sections and says when evidence is insufficient.
