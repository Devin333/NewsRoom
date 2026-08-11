## ADDED Requirements

### Requirement: LLM requests can declare structured output
The system SHALL allow callers to request JSON object or JSON schema structured output from an LLM provider.

#### Scenario: JSON object response format
- **WHEN** a request specifies `json_object`
- **THEN** the OpenAI-compatible payload includes a JSON object response format

#### Scenario: Output schema response format
- **WHEN** a request specifies an output schema
- **THEN** the OpenAI-compatible payload includes a JSON schema response format

### Requirement: Structured responses are normalized
The system SHALL parse structured JSON response text into `LLMResponse.structured_output`.

#### Scenario: Provider returns JSON object text
- **WHEN** a structured request receives JSON object text
- **THEN** the normalized response contains that object as structured output

#### Scenario: Provider returns invalid structured output
- **WHEN** a structured request receives invalid JSON
- **THEN** the client raises a non-retryable structured output parse error

### Requirement: Daily report drafting can consume structured output
The system SHALL prefer structured LLM output for daily live report drafts when available.

#### Scenario: LLM response contains structured report
- **WHEN** daily live drafting receives `structured_output`
- **THEN** it uses that object instead of reparsing raw text
