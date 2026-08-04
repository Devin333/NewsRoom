## MODIFIED Requirements

### Requirement: Stable API Error Envelope
The system SHALL wrap every API error, including unhandled internal exceptions, in a stable envelope containing `success`, `error`, `request_id`, and `schema_version`, where `error` includes `code`, `message`, `details`, `retryable`, `user_action_required`, and the same `request_id`. The response header, body, nested error, and write-audit record SHALL share one canonical request id, and unknown internal exceptions SHALL use a fixed safe public message.

#### Scenario: Validation error returns contract shape
- **WHEN** an API request fails validation
- **THEN** the response body contains the shared error envelope and preserves the request id

#### Scenario: Unhandled route exception returns contract shape
- **WHEN** an API route or dependency raises an unclassified internal exception
- **THEN** the response is a JSON 500 envelope with code `internal_error`
- **AND** the raw exception text and traceback are absent

#### Scenario: Generated request id survives an exception
- **WHEN** a request has no valid client request id and later fails internally
- **THEN** the id generated at request ingress is used by the response header, top-level body, nested error, and audit record

#### Scenario: Client request id survives an exception
- **WHEN** a request supplies a valid request id and later fails internally
- **THEN** the same client id is preserved by the response and audit record
