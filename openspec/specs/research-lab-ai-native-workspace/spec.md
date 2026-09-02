# research-lab-ai-native-workspace Specification

## Purpose
TBD - created by archiving change research-lab-ai-native-workspace. Update Purpose after archive.
## Requirements
### Requirement: Research Lab workspace
The system SHALL provide a research-oriented workspace at /projects/lab for creating, clarifying, generating, reviewing, and saving Projects Lab sessions.

#### Scenario: Start a session from a real-data-aware brief
- **WHEN** a user submits a non-empty trimmed problem on /projects/lab
- **THEN** the workspace SHALL show the submitted brief, source/data-state context, and selected case summary from real API data
- **AND** SHALL create the session through the existing Projects API client
- **AND** SHALL retain the problem draft when the mutation fails

#### Scenario: No active session
- **WHEN** no Lab session is active
- **THEN** the workspace SHALL show the brief composer and an explicit next-step empty state
- **AND** SHALL NOT show a fabricated conversation, solution, project, case, or source

### Requirement: Server-driven workflow feedback
The workspace SHALL use the Lab workflow contract to render stage, next action, unanswered work, and action availability.

#### Scenario: Clarification remains incomplete
- **WHEN** the API response has can_generate_solution=false and unanswered_question_ids is non-empty
- **THEN** the workspace SHALL show the unanswered work and a textual explanation
- **AND** SHALL not enable or submit Generate Solution

#### Scenario: Generation becomes available
- **WHEN** the API response has next_action=generate_solution and can_generate_solution=true
- **THEN** the workspace SHALL make Generate Solution available
- **AND** SHALL announce the available next action using a polite accessible status region

#### Scenario: Unknown workflow state
- **WHEN** the client receives an unknown current_stage or next_action
- **THEN** the workspace SHALL display a conservative recovery state
- **AND** SHALL not grant generate, save, adopt, archive, or publish capability based on that value

### Requirement: Truthful interaction feedback
The workspace SHALL communicate only actual request lifecycle information and SHALL preserve recoverable local input.

#### Scenario: Answer is being saved
- **WHEN** a user submits a clarification answer
- **THEN** only the related answer control SHALL enter pending state with aria-busy feedback
- **AND** previously completed workspace content SHALL remain available

#### Scenario: Answer mutation fails
- **WHEN** the answer API mutation fails
- **THEN** the answer text SHALL remain editable
- **AND** an actionable error SHALL be associated with the answer input
- **AND** the user SHALL be able to retry

#### Scenario: Solution generation is pending
- **WHEN** Generate Solution has an unresolved API request
- **THEN** the UI SHALL show actual generation pending feedback
- **AND** SHALL prevent duplicate generation submission
- **AND** SHALL NOT simulate streamed tokens, typing, hidden reasoning, or a false percentage

### Requirement: Auditable solution views
The workspace SHALL render generated solution data in readable, structured, and evidence-oriented views.

#### Scenario: Solution is available
- **WHEN** a generated session response contains generated_solution or solution_json
- **THEN** the workspace SHALL provide Summary, Structured, and Evidence Tabs
- **AND** Summary SHALL be the initial visible view
- **AND** Structured SHALL show bounded, locally scrollable formatted JSON

#### Scenario: Evidence is incomplete
- **WHEN** an evidence field, source line, case reference, or data policy is absent
- **THEN** the workspace SHALL state that the field is unavailable
- **AND** SHALL NOT infer or invent evidence

#### Scenario: Copy structured data
- **WHEN** a user activates the structured-data copy control
- **THEN** the workspace SHALL copy only the rendered structured solution data
- **AND** SHALL expose a success or failure status to keyboard and screen-reader users

### Requirement: Accessible graph context
The workspace SHALL provide graph context that is usable without visual SVG interpretation.

#### Scenario: Graph is rendered
- **WHEN** a session contains graph_state
- **THEN** the workspace SHALL provide a visible graph title and node/relationship count
- **AND** SHALL provide a text equivalent for nodes, relationships, and focus

#### Scenario: User requests node explanation
- **WHEN** a user requests an explanation for an available graph node
- **THEN** the workspace SHALL call the existing explain-node API
- **AND** SHALL render the returned explanation and related nodes
- **AND** a node explanation failure SHALL NOT block the rest of the Lab workflow

### Requirement: Responsive and accessible operation
The Lab workspace SHALL be usable across supported mobile and desktop viewport sizes with keyboard and assistive technology.

#### Scenario: Mobile view
- **WHEN** the viewport is below 768px wide
- **THEN** the workspace SHALL use a single-column layout with 16px minimum page gutter
- **AND** primary workflow actions SHALL remain visible and at least 44px high
- **AND** the document SHALL not require horizontal scrolling

#### Scenario: Keyboard path
- **WHEN** a keyboard user creates a session, answers questions, generates a solution, and saves it
- **THEN** every workflow control SHALL be reachable and operable without pointer input
- **AND** focus SHALL move to the next actionable step after successful mutation

### Requirement: Explicit data and save semantics
The workspace SHALL preserve existing real-data notices and distinguish saving from quality approval or publication.

#### Scenario: Data is degraded or empty
- **WHEN** Projects data_state is not ready or notices are present
- **THEN** the workspace SHALL render the existing degraded or empty state components
- **AND** SHALL not replace missing data with mock content

#### Scenario: Session is saved
- **WHEN** the API confirms a save operation
- **THEN** the workspace SHALL identify the result as saved, adopted, or archived according to the returned state
- **AND** SHALL NOT state or imply that the solution passed a quality gate or was published

