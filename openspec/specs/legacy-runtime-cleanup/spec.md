## Purpose
Define cleanup requirements for retiring obsolete board, paper, scoring, interface, and legacy test assets after Harness + Research replacements are accepted.
## Requirements
### Requirement: Stage Zero Audit Inventory
Stage 0 SHALL produce `docs/prd/harness-research-runtime/audit-inventory.md` with keep, adapt, and delete classifications for `framework`, `backend`, `interfaces`, `tests`, `openspec/specs`, and `docs/architecture`.

#### Scenario: Delete candidate has cleanup metadata
- **WHEN** an inventory row is categorized as `delete`
- **THEN** it MUST include a reason, replacement, deletion phase, and tests action

### Requirement: Preserve Useful Framework Assets

Legacy cleanup SHALL preserve or adapt useful domain-neutral assets for LLM, tools, memory, skills, artifacts, events, workers, scoring, governance, shared primitives, specs, and Graph utilities when they serve Harness + Research. Useful behavior currently implemented inside a retired Workflow module SHALL move to its explicit owner before the old module is deleted; the Workflow module, public symbol and compatibility import SHALL not be preserved merely because behavior was reused.

#### Scenario: Neutral framework asset is kept or adapted

- **WHEN** a framework capability has reusable runtime value and no backend dependency
- **THEN** the inventory MUST classify its behavior as `keep` or `adapt` with a target owner
- **AND** cleanup MUST remove the retired Workflow container after all callers use that owner

### Requirement: Delete Obsolete Legacy Business Assets
Legacy business assets that exist only for old board, paper_radar, old paper API, old reader payload, old UI compatibility, or superseded control flow SHALL be deleted in stage 8 or stage 9 after replacement Harness + Research coverage exists.

#### Scenario: Old paper_radar compatibility is removed
- **WHEN** Research service and API replacements are accepted
- **THEN** cleanup MUST remove old paper_radar compatibility paths that no longer serve Harness + Research
- **AND** cleanup MUST NOT keep adapters solely for old paper payloads or old UI consumers

### Requirement: Delete Obsolete Interface Assets
Old paper-specific service and API routes SHALL be deleted when Research backend interfaces replace them. Interface layers SHALL call application services rather than reaching into executors, stores, or old business runners directly.

#### Scenario: Old papers router is retired
- **WHEN** Research API routes provide the accepted backend surface
- **THEN** `interfaces/api/routers/papers.py` and old `interfaces/services/paper_*.py` paths marked for deletion MUST be removed or replaced according to the inventory

### Requirement: Replace Or Remove Legacy Tests
Tests for old behavior SHALL be replaced with Harness + Research tests or deleted only when the old behavior is explicitly deprecated. Tests MUST NOT be deleted to hide unrelated failures.

#### Scenario: Deprecated paper API test is removed with replacement
- **WHEN** a paper API behavior is deprecated by Research API behavior
- **THEN** the old test MAY be deleted in the cleanup phase
- **AND** the replacement Research test MUST cover the new accepted behavior

### Requirement: Cleanup Maintains Architecture Boundaries
Cleanup SHALL enforce that framework does not import backend, interfaces, or concrete infrastructure; `backend/research` does not import old paper_radar, interfaces, or concrete infrastructure; and interface services remain entry-layer coordinators.

#### Scenario: Boundary test blocks compatibility leak
- **WHEN** a compatibility adapter introduces a forbidden dependency across these boundaries
- **THEN** boundary tests MUST fail
- **AND** cleanup MUST remove or relocate the adapter rather than preserving the leak

### Requirement: Retire Obsolete Agent Shared-Session Runtime
After Harness durable transcript replacement acceptance, cleanup SHALL remove `framework/agent/session`, `framework/memory/session`, their dedicated tests, `AgentSessionContextPolicy`, AgentLoop shared-session prompt injection, and special subagent metadata propagation. The runtime MUST NOT retain a compatibility re-export, fallback store, no-op implementation, hidden workspace input, or feature flag that recreates the retired state plane.

#### Scenario: Repository is inspected after retirement
- **WHEN** architecture checks inspect production and test source
- **THEN** the obsolete package directories, retired symbols, imports, exports, hooks, and dedicated tests MUST be absent
- **AND** production MUST expose no replacement compatibility layer or implicit shared-session fallback

#### Scenario: Stale AgentSpec policy is loaded
- **WHEN** `AgentSpec.from_dict()` receives the retired `session_context_policy` key
- **THEN** it MUST reject the payload with a stable validation error
- **AND** it MUST NOT silently ignore the policy or assemble shared session content

#### Scenario: Legacy subagent metadata contains session id
- **WHEN** a legacy `SubAgentTask` carries `session_id` only in metadata
- **THEN** `_child_inputs()` MUST NOT promote that value into child inputs
- **AND** normal run and workflow correlation metadata MUST remain available through their existing owners

### Requirement: Agent Execution Has No Shared-Session State Plane
`AgentLoop` and `AgentRunner` SHALL execute bounded agent turns without accepting a shared-session store, workspace, context assembler, or hidden workspace input. `AgentRunner` MUST NOT gain session persistence authority as part of this retirement.

#### Scenario: AgentLoop and AgentRunner signatures are inspected
- **WHEN** architecture checks inspect constructors and run methods
- **THEN** neither public surface SHALL accept session store/workspace/context-assembler parameters
- **AND** AgentLoop MUST NOT inspect `_agent_session_workspace` or inject `shared_session_context`

#### Scenario: Ordinary AgentSpec roundtrips
- **WHEN** an AgentSpec without retired fields is serialized and restored
- **THEN** the roundtrip MUST preserve its supported fields
- **AND** the serialized payload MUST NOT contain `session_context_policy`

### Requirement: Preserve Independently Owned Session Capabilities

Retirement SHALL preserve Harness RAG sessions, Research reading sessions, auth/project sessions, persisted conversations, conversation cursors and compaction, and generic Graph run/node correlation. Cleanup MUST be scoped by package ownership and retired symbol, not by the text `session` or `session_id` alone.

#### Scenario: Retained session suites run

- **WHEN** RAG, Research, authentication/project, conversation cursor, conversation compaction, and Graph correlation regressions execute after cleanup
- **THEN** their accepted behavior MUST remain available
- **AND** none of those modules may import the retired agent-session or Workflow runtime packages

### Requirement: Preserve Superseded Shared-Session History Without Spec Sync
The completed `paper-agent-shared-session-analysis` change SHALL be archived as superseded history with spec synchronization skipped. Its `agent-shared-session`, paper orchestrator, and SQLite session requirements MUST NOT be merged into canonical specs.

#### Scenario: Historical change is archived
- **WHEN** maintainers archive `paper-agent-shared-session-analysis`
- **THEN** they MUST use `openspec archive paper-agent-shared-session-analysis --skip-specs`
- **AND** canonical spec content checksums before and after the archive MUST be identical

### Requirement: Historical Agent Session Data Is Operator Owned

After the obsolete agent shared-session runtime is retired, NewsRoom SHALL treat any pre-existing `.newsroom/paper-agent-sessions.sqlite3` or equivalent legacy session database as `orphaned historical data`. Production startup, migrations, cleanup jobs, and replacement Harness code MUST NOT create, read, import, rewrite, archive, or delete that data automatically. A release or operations note MUST state that retention, external archive, and removal are explicit operator decisions subject to local policy.

#### Scenario: NewsRoom starts after retirement

- **WHEN** an installation has no legacy session database or still contains a pre-retirement database
- **THEN** production runtime MUST neither create nor access the retired database path
- **AND** Harness durable transcript startup MUST be independent from that file

#### Scenario: Operator reviews orphaned historical data

- **WHEN** an operator prepares retention or cleanup after the retirement release
- **THEN** the operations note MUST identify the old path and explain that NewsRoom will not delete it automatically
- **AND** the operator MAY retain, externally archive, or remove it only through an explicit out-of-band decision
