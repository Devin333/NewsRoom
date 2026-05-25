## ADDED Requirements

### Requirement: Browser paper requests use BFF routes
The system SHALL make browser-visible paper list, detail, and summary requests through `/api/papers...` routes instead of `/api/v1/papers...`.

#### Scenario: Browser fetches papers
- **WHEN** the paper stream requests papers from the browser
- **THEN** the request path SHALL start with `/api/papers`

#### Scenario: BFF forwards with server credentials
- **WHEN** a BFF paper route forwards to FastAPI
- **THEN** backend API tokens SHALL be read only from server environment variables

### Requirement: Backend paper fields are preserved
The system SHALL treat backend `PublicPaper` DTOs as authoritative and SHALL NOT re-normalize them through local fallback cache conversion.

#### Scenario: API paper contains optional fields
- **WHEN** a backend paper includes implementations, benchmarks, heat score, AI summary, arXiv id, or project URL
- **THEN** frontend paper loading SHALL preserve those fields

### Requirement: PaperRadar artifacts are preferred data sources
The backend paper service SHALL prefer the latest valid PaperRadar artifact over static paper cache data and SHALL filter non-paper artifacts before producing public papers.

#### Scenario: Latest artifact contains mixed sources
- **WHEN** a PaperRadar artifact includes paper and non-paper source cards
- **THEN** only true paper records SHALL be exposed as public papers

### Requirement: Reader payload is available
The backend paper service SHALL provide a reader payload for a paper using public paper metadata, cached or generated AI summary, lightweight sections, related entities, and quality metadata.

#### Scenario: Reader payload requested
- **WHEN** a paper reader page loads a known paper
- **THEN** it SHALL receive the paper, sections, summary availability, related entity placeholders, and quality status without raw private fields

### Requirement: Public DTOs are redacted
The system SHALL prevent raw/private fields from appearing in public Paper Reader DTOs.

#### Scenario: Source contains private keys
- **WHEN** a source payload contains `raw_payload`, `raw_content`, `raw_html`, `full_text`, `secret`, `api_key`, `token`, or `authorization`
- **THEN** those fields SHALL be removed from public paper, source, evidence, and reader payloads
