# business-cross-board-intelligence Specification

## Purpose
TBD - created by archiving change business-final-target-0-to-1. Update Purpose after archive.
## Requirements
### Requirement: Cross-board intelligence services
Cross-board intelligence SHALL provide relation views, technology journeys, technology radar output, insight generation, policy profiles, and regression guard checks without collecting raw data.

#### Scenario: Technology journey from processed relations
- **WHEN** processed relations include proposes, implements, discusses, and adopts relations for a technology
- **THEN** cross-board services build a technology journey from those relations without calling source collectors

### Requirement: Cross-board evidence blocking
Cross-board insights MUST require evidence relations and multi-board support for strong insights, and MUST block unsupported or weak relation-chain claims.

#### Scenario: Unsupported insight is blocked
- **WHEN** an insight candidate has no evidence relation or only weak single-board support
- **THEN** the cross-board regression guard returns a blocking result

