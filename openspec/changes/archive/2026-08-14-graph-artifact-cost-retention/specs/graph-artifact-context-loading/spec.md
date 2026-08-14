## ADDED Requirements

### Requirement: Approved context load usage is durably accounted
Production context loading SHALL commit one sanitized usage fact after exact load-result verification and before returning admitted context. The fact SHALL bind tenant/run/graph/node, plan checksum, result checksum, purpose, load mode, policy version, actual loaded bytes/tokens, and outcome. Repeating the same plan/result SHALL be idempotent, and usage failure in governed production modes SHALL fail the load with a typed sanitized error.

#### Scenario: Full context load succeeds
- **WHEN** an approved full load verifies all artifacts and fits its budgets
- **THEN** one usage fact records exact loaded bytes/tokens before the context result is returned

#### Scenario: Summary-only load is repeated after restart
- **WHEN** the same summary-only plan/result is rebuilt after restart
- **THEN** the original usage identity is reused and summary bytes/tokens are charged once

#### Scenario: Usage ledger is unavailable
- **WHEN** a production governed context load succeeds physically but its durable usage fact cannot be committed
- **THEN** no accounted context result is returned and the failure contains no artifact body
