## ADDED Requirements

### Requirement: Answer gate failures can drive bounded supplemental retrieval
Harness RAG SHALL use unsupported claims from failed deterministic answer gates to perform a controlled supplemental retrieval round before final abstention when generation attempts and replan budget remain.

#### Scenario: Supplemental retrieval produces a verified answer
- **WHEN** generation policy enables more than one attempt
- **AND** the first answer candidate fails answer gates with unsupported claims
- **AND** a controlled supplemental round accepts additional evidence and produces a verified context pack
- **AND** the next answer candidate passes answer gates
- **THEN** the session SHALL return status `answered`
- **AND** the transcript SHALL record the unsupported claims and supplemental round events

#### Scenario: Supplemental retrieval still cannot support the answer
- **WHEN** generation policy enables more than one attempt
- **AND** an answer candidate fails answer gates with unsupported claims
- **AND** a controlled supplemental round runs
- **AND** the next answer candidate still fails answer gates
- **THEN** the session SHALL return status `abstained`
- **AND** the final decision SHALL include answer gate failure details

#### Scenario: Supplemental retrieval is blocked by budget
- **WHEN** an answer candidate fails answer gates with unsupported claims
- **AND** no controlled replan budget remains
- **THEN** the session SHALL return status `abstained`
- **AND** it SHALL NOT run another retrieval step or answer attempt

### Requirement: Paper answer sessions enable one retry
Production paper RAG sessions SHALL configure generated-answer sessions with a single supplemental retry when an answer worker is enabled.

#### Scenario: Factory enables two generation attempts
- **WHEN** `build_paper_rag_session(with_answer_worker=True)` builds a session
- **THEN** the session generation policy SHALL enable generation
- **AND** it SHALL set `max_attempts` to `2`
