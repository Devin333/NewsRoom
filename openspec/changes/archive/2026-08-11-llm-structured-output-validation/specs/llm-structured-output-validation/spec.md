## ADDED Requirements

### Requirement: LLM layer validates structured output schema
The system SHALL validate parsed structured output against `LLMRequest.output_schema`
when a schema is supplied.

#### Scenario: Structured output satisfies schema
- **WHEN** provider JSON contains required fields with valid types
- **THEN** the response includes the parsed structured output

#### Scenario: Structured output violates schema
- **WHEN** provider JSON misses a required field or has the wrong type
- **THEN** the client raises a non-retryable structured validation provider error

#### Scenario: JSON object mode without schema remains parse-only
- **WHEN** `response_format=json_object` is used without `output_schema`
- **THEN** the client parses JSON without schema validation
