## Why

The LLM target architecture treats structured output as a first-class capability. The current LLM request model cannot declare JSON output requirements, and the OpenAI-compatible client only returns raw text.

## What Changes

- Add response format and output schema fields to `LLMRequest`.
- Add `structured_output` to `LLMResponse`.
- Translate JSON object and JSON schema requests into OpenAI-compatible `response_format` payloads.
- Parse structured JSON responses into `LLMResponse.structured_output`.
- Use structured output in the daily live report request path when available.

## Out Of Scope

- Full JSON Schema validation.
- Provider-specific repair loops.
- Tool-call-as-output strategy.
- Streaming structured output.
