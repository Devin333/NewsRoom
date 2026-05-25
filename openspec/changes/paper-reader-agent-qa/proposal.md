## Why

Paper Reader now has a stable list/detail/reader surface, but "Ask this paper" is still a disabled placeholder. Phase 3 needs a safe first Reader Agent that can answer questions from public paper sections without blocking the core reading experience.

## What Changes

- Add a Paper Reader Agent boundary that answers single-paper questions using reader payload sections, metadata, summaries, and evidence refs.
- Add backend API and Next.js BFF routes for `POST /papers/{paper_id}/ask` style requests.
- Add frontend API client types and an interactive Ask this paper panel on `/papers/[slug]`.
- Cache deterministic answers by paper, question, locale, and source hash.
- Keep failure isolated: answer errors do not break PDF rendering, paper metadata, or reader payload display.

## Capabilities

### New Capabilities
- `paper-reader-agent-qa`: Single-paper Reader Agent Q&A using public reader sections and cited evidence.

### Modified Capabilities

## Impact

- Backend services: `PapersApplicationService`, new Paper Reader Agent helper/models, API route tests.
- Frontend: paper API client/types, Next.js BFF ask route, reader page Ask panel, tests.
- Security: public DTO redaction still applies; answers cite public sections/evidence only.
