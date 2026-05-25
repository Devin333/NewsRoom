## ADDED Requirements

### Requirement: Reader Agent answers single-paper questions
The system SHALL accept a question for one known paper and return an answer grounded in that paper's public reader payload.

#### Scenario: Known paper question is answered
- **WHEN** a client asks a question for a known paper
- **THEN** the response SHALL include an answer, citations, confidence, cached status, and generated timestamp

#### Scenario: Unknown paper is requested
- **WHEN** a client asks a question for an unknown paper id or slug
- **THEN** the API SHALL return a not-found error without creating an answer

### Requirement: Reader Agent cites public evidence
The system SHALL cite public sections, evidence refs, or source refs used to create the answer.

#### Scenario: Answer uses reader sections
- **WHEN** the answer is derived from reader sections
- **THEN** citations SHALL include section identifiers and text excerpts

#### Scenario: Source payload contains private fields
- **WHEN** a source or evidence object contains raw/private fields
- **THEN** the answer payload SHALL NOT include raw_payload, raw_content, raw_html, full_text, secret, api_key, token, or authorization fields

### Requirement: Reader Agent failure does not block reading
The frontend SHALL keep the reader page usable when Ask this paper fails.

#### Scenario: Ask request fails
- **WHEN** the Ask this paper request returns an error
- **THEN** the page SHALL continue showing the PDF/text fallback, paper metadata, summary panel, and a retryable Ask error state

### Requirement: Browser Reader Agent requests use BFF routes
The browser SHALL submit Ask this paper requests through `/api/papers...` BFF routes instead of FastAPI `/api/v1...` routes.

#### Scenario: Browser submits a question
- **WHEN** the reader page asks a paper question
- **THEN** the request path SHALL start with `/api/papers/`
