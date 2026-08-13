## MODIFIED Requirements

### Requirement: Nested logical operations have stable distinct identities

The runtime SHALL derive each nested logical-operation key from the parent key, child kind, and stable child identifier. Sibling logical operations SHALL have distinct keys, and retries of one logical operation SHALL reuse its key. Each logical operation SHALL own a `LocalRetryBudget`; a root-scoped `RetryCreditLedger` MAY limit the total number of retries but SHALL NOT replace local attempt numbering or resource ownership.

#### Scenario: Sibling Tool calls

- **WHEN** two Tool calls execute under the same Graph activity attempt
- **THEN** they receive different idempotency keys, independent local attempt counters, and no shared attempt/fence sequence even if they share the same parent context

#### Scenario: Retry of one Tool call

- **WHEN** one Tool call is retried
- **THEN** every attempt uses the same Tool-call idempotency key, a distinct attempt ID, and an incremented local attempt number while its parent Graph activity attempt number remains unchanged

### Requirement: Write fencing is issued by the protected resource

The Graph node-instance output resource SHALL atomically issue a monotonically increasing lease bound to the unique owner of each admitted activity attempt. A staged node-output write SHALL commit only while both its lease generation and owner match the current resource lease. Caller-provided budget generations, retry credits, Graph sequence values, or generic attempt sequences SHALL NOT establish write ownership.

#### Scenario: Independent controllers request the same local generation

- **WHEN** two independently budgeted attempts begin writes for the same Graph node instance
- **THEN** the output resource issues different ordered leases and rejects writes or commits from the superseded owner, regardless of either attempt's local number or retry credit

#### Scenario: Stale owner commits after replacement

- **WHEN** a newer owner acquires the node-output lease before an older staged write commits
- **THEN** the older attempt raises a typed stale-attempt error and publishes no staged values

### Requirement: Indeterminate descendants cannot publish normal output

An outer Graph activity attempt SHALL NOT commit staged node output or publish normal business artifacts after any descendant is marked indeterminate. The runtime SHALL retain diagnostic metadata through error envelopes or events without representing it as a successful artifact, and remaining local/root retry budget SHALL not override this gate.

#### Scenario: Parallel branch remains unconfirmed

- **WHEN** a parallel branch times out and remains alive beyond cancellation grace
- **THEN** the parent result is indeterminate, no branch-result artifact is published, and no parent retry is admitted solely because budget remains

#### Scenario: Late node-output write

- **WHEN** a superseded activity attempt writes or commits after timeout
- **THEN** the node-output resource rejects the operation and the visible Graph state remains unchanged
