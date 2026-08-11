## Design

`LLMRequest` gains optional `response_format`, `output_schema`, and `output_schema_name` fields. `response_format` may be a provider-style dict or a shorthand string such as `json_object`.

When `output_schema` is present and no explicit response format is provided, `OpenAICompatibleClient` sends an OpenAI-compatible JSON schema response format. When `response_format` is a string, the client sends `{"type": response_format}`.

When a request expects structured output, the normalized response parses message content as JSON and stores the object on `LLMResponse.structured_output`. Invalid JSON or non-object structured payloads raise a non-retryable provider error with `structured_output_parse_error`.

The daily intelligence live report request uses JSON object mode and prefers `response.structured_output`, falling back to the existing text parser for compatible callers.

## Validation

Tests assert payload translation for JSON object and JSON schema response formats, successful structured parsing, non-retryable structured parse failures, redacted serialization of structured output, and daily runner preference for structured output. A smoke script uses an injected OpenAI-compatible transport.
