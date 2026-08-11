## MODIFIED Requirements

### Requirement: LLM layer validates structured output schema
The system SHALL compile `LLMRequest.output_schema` into a canonical `draft2020-12-local-v1` structured-output contract before validating a parsed structured object. The contract MUST use `jsonschema.Draft202012Validator`, allow only same-document `$defs` / `$ref` resolution, apply configured schema and instance resource limits, and return bounded stable diagnostics. Validation failure MUST raise a non-retryable deterministic structured validation error and MUST NOT expose the object as accepted `structured_output`.

#### Scenario: Structured output satisfies a nested local schema
- **WHEN** provider JSON satisfies required fields, nested local `$ref` definitions, types, combinations, and validation constraints
- **THEN** the response includes the parsed structured output

#### Scenario: Structured output violates schema semantics
- **WHEN** provider JSON violates a required field, type, combination, local reference, numeric/boolean equality rule, or other configured Draft 2020-12 assertion
- **THEN** the client raises a non-retryable structured validation error with bounded diagnostics

#### Scenario: Schema is invalid or unsafe
- **WHEN** `output_schema` is invalid, has a forbidden external reference, uses an unapproved extension, or exceeds configured schema limits
- **THEN** contract preflight fails before a Provider call is attempted

#### Scenario: JSON object mode without schema remains parse-only
- **WHEN** `response_format=json_object` is used without `output_schema`
- **THEN** the client applies strict JSON-object decoding without schema validation

## ADDED Requirements

### Requirement: Pydantic structured-output contracts retain typed validation
The system SHALL accept a Pydantic model class as an output-schema source, derive its JSON Schema for the local contract, and run Pydantic typed validation after Draft 2020-12 validation. Nested Pydantic `$defs` / `$ref` schemas and model-level validation failures MUST be deterministic validation failures.

#### Scenario: Nested Pydantic model is invalid
- **WHEN** a provider object violates a nested Pydantic model field or model-level validator
- **THEN** the client raises a non-retryable structured validation error and does not expose accepted structured output

#### Scenario: Pydantic model is valid
- **WHEN** a provider object satisfies both the exported Draft schema and Pydantic typed validation
- **THEN** the response exposes the validated JSON-object representation as structured output
