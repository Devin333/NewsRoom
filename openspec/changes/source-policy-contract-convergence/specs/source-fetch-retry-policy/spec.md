## MODIFIED Requirements

### Requirement: Source fetch policy retries transient fetch failures
The system SHALL use the infrastructure `SourceFetchPolicy` retry classifier for
every Source fetch operation. `retry_times` SHALL mean retries after the first
operation invocation, and an exception raised by an invoked operation SHALL
expose the actual invocation count. Policy construction and post-fetch parsing
are outside this retry boundary.

#### Scenario: Configured HTTP 5xx succeeds after retry
- **WHEN** a Source fetch receives an HTTP 5xx status included in
  `retry_on_status_codes` and a later attempt succeeds within `retry_times`
- **THEN** the entry point returns fetched source items without a SourceError

#### Scenario: HTTP 4xx is not configured for retry
- **WHEN** a Source fetch receives an HTTP 4xx status not included in
  `retry_on_status_codes`
- **THEN** the entry point returns or raises the structured fetch error after one
  attempt

#### Scenario: Configured transient HTTP 4xx is retried
- **WHEN** a Source fetch receives HTTP 429 and 429 is included in
  `retry_on_status_codes`
- **THEN** the fetch is retried within the configured retry budget

#### Scenario: Custom policy can retry HTTP 404
- **WHEN** a Source fetch receives HTTP 404 and 404 is included in
  `retry_on_status_codes`
- **THEN** the operation is retried
- **AND** the final SourceError reports `retryable=True`

#### Scenario: Custom policy can disable HTTP 503 retry
- **WHEN** a Source fetch receives HTTP 503 and 503 is absent from
  `retry_on_status_codes`
- **THEN** the operation stops after one invocation
- **AND** the final SourceError reports `retryable=False`

#### Scenario: Timeout and URL transport failures are retried
- **WHEN** a Source fetch raises `TimeoutError`, a timeout-shaped `URLError`, or
  another `URLError`
- **THEN** the fetch is retried within the configured retry budget

#### Scenario: Deterministic value failure is not retried
- **WHEN** an invoked Source fetch operation raises `ValueError` for response
  size, redirect, content type, or deterministic robots policy
- **THEN** the failure is returned after one operation invocation

#### Scenario: Other fetch exception retains retryable default
- **WHEN** a Source fetch callable raises any other `Exception`, including
  `KeyError`, `TypeError`, or `AssertionError`, that is not otherwise classified
  by the retry matrix
- **THEN** the fetch is retried within the configured retry budget

#### Scenario: Robots policy denial is not retried
- **WHEN** robots policy explicitly disallows a Source URL
- **THEN** `RobotsDisallowedError` is returned after one operation invocation

#### Scenario: Robots transport failure follows fetch retry matrix
- **WHEN** loading `robots.txt` instead fails with a retryable HTTP, timeout, or
  URL transport exception
- **THEN** that transport failure follows the canonical retry matrix

#### Scenario: Invalid policy performs no fetch attempt
- **WHEN** Source fetch policy construction or validation fails
- **THEN** the network operation is not invoked
- **AND** no synthetic fetch-attempt metadata is required

#### Scenario: Parse failure does not re-enter fetch retries
- **WHEN** parsing fails after a Source fetch operation succeeds
- **THEN** the parse failure is classified by Source taxonomy
- **AND** the successful network operation is not repeated

#### Scenario: Retry attempts are exhausted
- **WHEN** all `retry_times + 1` operation invocations fail with a retryable fetch exception
- **THEN** the entry point returns or raises the final structured fetch error
- **AND** attempt metadata equals `retry_times + 1`

#### Scenario: Zero retry budget performs one attempt
- **WHEN** `retry_times` is zero and the first operation fails
- **THEN** the operation is called exactly once
- **AND** final attempt metadata equals one
