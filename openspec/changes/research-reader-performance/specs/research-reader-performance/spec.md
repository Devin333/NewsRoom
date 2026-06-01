## ADDED Requirements

### Requirement: Reader server loading is bounded
The Research Reader read route SHALL avoid waiting indefinitely for compiled-document or compile-status APIs before returning a user-visible payload.

#### Scenario: Compiled document API is slow
- **WHEN** `/papers/{slug}/read` requests a known published paper and the compiled document API exceeds the Reader document wait budget
- **THEN** the route SHALL return a fallback Reader payload based on the real paper record
- **AND** the payload SHALL include a diagnostic that the compiled document is not currently available
- **AND** the route SHALL NOT fabricate document sections.

#### Scenario: Slug resolves after a document timeout
- **WHEN** the initial document request times out for a slug and the slug resolves to a real paper id
- **THEN** the loader SHALL NOT immediately spend another document wait budget retrying the same request by id
- **AND** the loader SHALL return the real-paper fallback payload.

### Requirement: Open Reader renders long documents progressively
The compiled Open Reader page SHALL render the first useful body sections before mounting the entire paper body.

#### Scenario: Long compiled document opens
- **WHEN** a compiled Reader payload contains more sections than the initial render window
- **THEN** the first window of sections SHALL be visible immediately
- **AND** later sections SHALL mount progressively during idle time or fallback scheduling
- **AND** the body SHALL eventually include all real compiled sections.

#### Scenario: User jumps to a later section
- **WHEN** a user selects a table-of-contents item whose section has not mounted yet
- **THEN** the Reader SHALL expand rendering through that section
- **AND** scroll to the selected real section after it is mounted.

### Requirement: Non-critical Reader sync is deferred
The Open Reader SHALL defer personal reader material synchronization until after the first render opportunity.

#### Scenario: Reader mounts
- **WHEN** a Reader page first renders public paper text
- **THEN** it SHALL NOT synchronously request reader materials during the first render path
- **AND** it SHALL request real reader materials during an idle or fallback scheduled task.
