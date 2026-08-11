# llm-structured-output Specification

## Purpose
TBD - created by archiving change llm-structured-output. Update Purpose after archive.
## Requirements
### Requirement: LLM requests can declare structured output
The system SHALL allow callers to request JSON object or JSON schema structured output from an LLM provider.

#### Scenario: JSON object response format
- **WHEN** a request specifies `json_object`
- **THEN** the OpenAI-compatible payload includes a JSON object response format

#### Scenario: Output schema response format
- **WHEN** a request specifies an output schema
- **THEN** the OpenAI-compatible payload includes a JSON schema response format

### Requirement: Structured responses are normalized
The system SHALL normalize structured response text into `LLMResponse.structured_output` only after a strict JSON-object decoder accepts the provider content. The decoder MUST reject malformed JSON, non-finite number tokens, duplicate object keys, non-object roots, and configured response limits, and the client MUST raise a non-retryable structured output parse error without exposing an accepted structured object.

#### Scenario: Provider returns strict JSON object text
- **WHEN** a structured request receives a finite JSON object within configured limits
- **THEN** the normalized response contains that object as `structured_output`

#### Scenario: Provider returns non-standard or ambiguous JSON
- **WHEN** a structured request receives `NaN`, `Infinity`, a duplicate object key, malformed JSON, or a non-object root
- **THEN** the client raises a non-retryable structured output parse error and does not produce `structured_output`

### Requirement: Daily report drafting can consume structured output
The system SHALL prefer structured LLM output for daily live report drafts when available.

#### Scenario: LLM response contains structured report
- **WHEN** daily live drafting receives `structured_output`
- **THEN** it uses that object instead of reparsing raw text
