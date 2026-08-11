## Why

The LLM layer parses structured JSON into `LLMResponse.structured_output`, but it
does not validate the parsed object against `LLMRequest.output_schema`.
`04-LLM_LAYER_TARGET_ARCHITECTURE.md` explicitly allows basic schema validation
in the LLM layer while leaving final acceptance to AgentLoop or quality gates.

## What Changes

- Add a small structured output schema validator for common JSON Schema fields.
- Validate provider structured output when `output_schema` is supplied.
- Raise non-retryable provider errors on schema mismatches.

## Out Of Scope

- Full JSON Schema draft compliance.
- Business-level acceptance of the structured output.
- Schema retry loops.
