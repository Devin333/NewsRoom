# business-cross-board-intelligence Specification

## Purpose
TBD - created by archiving change business-final-target-0-to-1. Update Purpose after archive.
## Requirements
### Requirement: Cross-board intelligence services
Cross-board intelligence SHALL provide relation views, technology journeys, technology radar output, insight generation, policy profiles, regression guard checks, and deterministic graph/path intelligence without collecting raw data.

#### Scenario: Technology journey from processed relations
- **WHEN** processed relations include proposes, implements, discusses, and adopts relations for a technology
- **THEN** cross-board services build a technology journey from those relations without calling source collectors

#### Scenario: Complete cross-board graph path
- **WHEN** processed relations and board outputs support a `paper -> project -> community -> ai_news` technology journey
- **THEN** cross-board graph intelligence returns an ordered path with board sequence, evidence relation ids, confidence, path score, quality checks, and no blocking guard result

### Requirement: Cross-board evidence blocking
Cross-board insights MUST require evidence relations, multi-board support, ordered stage support, non-contradictory evidence, and sufficient confidence for strong insights, and MUST block unsupported or weak relation-chain claims.

#### Scenario: Unsupported insight is blocked
- **WHEN** an insight candidate has no evidence relation or only weak single-board support
- **THEN** the cross-board regression guard returns a blocking result

#### Scenario: Bad path evidence is blocked or warned
- **WHEN** a path is missing required stages, has contradictory evidence, has duplicate evidence, or has low confidence
- **THEN** missing stages and contradictions produce blocking reasons while duplicate or low-confidence evidence produces warnings and does not inflate path score

