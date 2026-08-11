## Design

`validate_structured_output(value, schema)` supports the subset already used by
News contracts:

- `type` including object, array, string, integer, number, boolean, and null.
- `required` object properties.
- nested `properties`.
- array `items`.
- `enum`.
- `additionalProperties: false`.

`OpenAICompatibleClient` calls the validator after parsing structured JSON when
`request.output_schema` is present. Validation errors are wrapped as
`LLMProviderError` with `structured_output_validation_error` and `retryable=False`.

This keeps the LLM layer responsible for provider/schema hygiene only; output
acceptance remains with the caller.

## Compatibility

Existing `response_format="json_object"` behavior remains parse-only because no
schema is provided.
