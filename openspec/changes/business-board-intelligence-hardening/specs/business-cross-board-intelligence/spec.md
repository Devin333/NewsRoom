## MODIFIED Requirements

### Requirement: Cross-board evidence blocking
Cross-board insights MUST require evidence relations and multi-board support for strong insights, and MUST block unsupported, weak, duplicated, contradictory, or broken relation-chain claims.

#### Scenario: Unsupported insight is blocked
- **WHEN** an insight candidate has no evidence relation or only weak single-board support
- **THEN** the cross-board regression guard returns a blocking result

#### Scenario: Broken technology journey is blocked
- **WHEN** a technology journey skips required evidence stages for a strong emergence claim
- **THEN** the cross-board guard records blocking reasons and the insight is not promoted as strong

## ADDED Requirements

### Requirement: Ordered technology journey
Technology journey generation SHALL order evidence stages as research proposal, project implementation, community discussion, and product or news adoption when matching relations exist.

#### Scenario: Journey stages follow evidence chain
- **WHEN** relations contain proposes, implements, discusses, and adopts evidence for the same technology
- **THEN** the journey returns stages in that order with relation evidence ids and source object refs
