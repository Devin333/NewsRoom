## MODIFIED Requirements

### Requirement: Structured responses are normalized
The system SHALL normalize structured response text into `LLMResponse.structured_output` only after a strict JSON-object decoder accepts the provider content. The decoder MUST reject malformed JSON, non-finite number tokens, duplicate object keys, non-object roots, and configured response limits, and the client MUST raise a non-retryable structured output parse error without exposing an accepted structured object.

#### Scenario: Provider returns strict JSON object text
- **WHEN** a structured request receives a finite JSON object within configured limits
- **THEN** the normalized response contains that object as `structured_output`

#### Scenario: Provider returns non-standard or ambiguous JSON
- **WHEN** a structured request receives `NaN`, `Infinity`, a duplicate object key, malformed JSON, or a non-object root
- **THEN** the client raises a non-retryable structured output parse error and does not produce `structured_output`
