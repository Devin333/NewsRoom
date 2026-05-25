## 1. Backend Reader Agent

- [x] 1.1 Add Reader Agent DTOs and deterministic answer builder.
- [x] 1.2 Add `PapersApplicationService.ask_paper` with cache and redaction.
- [x] 1.3 Add FastAPI `POST /api/v1/papers/{paper_id}/ask` route.

## 2. Frontend BFF and Client

- [x] 2.1 Add Next.js BFF `POST /api/papers/[paperId]/ask`.
- [x] 2.2 Extend paper frontend types and API client with ask request/response.

## 3. Reader UI

- [x] 3.1 Replace disabled Ask this paper placeholder with interactive ask panel.
- [x] 3.2 Show loading, error, empty, cached, confidence, and citation states.

## 4. Tests and Validation

- [x] 4.1 Add backend tests for answers, citations, cache, unknown paper, and redaction.
- [x] 4.2 Add frontend tests for BFF path and reader ask states.
- [x] 4.3 Run OpenSpec validation, backend paper tests, frontend papers tests, typecheck, build, and targeted reader e2e smoke.
