## MODIFIED Requirements

### Requirement: Preserve Useful Framework Assets

Legacy cleanup SHALL preserve or adapt useful domain-neutral assets for LLM, tools, memory, skills, artifacts, events, workers, scoring, governance, shared primitives, specs, and Graph utilities when they serve Harness + Research. Useful behavior currently implemented inside a retired Workflow module SHALL move to its explicit owner before the old module is deleted; the Workflow module, public symbol and compatibility import SHALL not be preserved merely because behavior was reused.

#### Scenario: Neutral framework asset is kept or adapted

- **WHEN** a framework capability has reusable runtime value and no business dependency
- **THEN** the inventory MUST classify its behavior as `keep` or `adapt` with a target owner
- **AND** cleanup MUST remove the retired Workflow container after all callers use that owner

### Requirement: Preserve Independently Owned Session Capabilities

Retirement SHALL preserve Harness RAG sessions, Research reading sessions, auth/project sessions, persisted conversations, conversation cursors and compaction, and generic Graph run/node correlation. Cleanup MUST be scoped by package ownership and retired symbol, not by the text `session` or `session_id` alone.

#### Scenario: Retained session suites run

- **WHEN** RAG, Research, authentication/project, conversation cursor, conversation compaction, and Graph correlation regressions execute after cleanup
- **THEN** their accepted behavior MUST remain available
- **AND** none of those modules may import the retired agent-session or Workflow runtime packages
