## ADDED Requirements

### Requirement: Productized board service entrypoints
BoardApplicationService SHALL provide `run_board`, `run_all_boards`, and `build_productized_cross_board_output` entrypoints while preserving existing list/build/attach methods.

#### Scenario: Productized board entrypoint runs supported boards
- **WHEN** an interface caller invokes `run_board` for a supported primary board
- **THEN** the service returns a RunResult from the business board runner and rejects unsupported board types with ValueError

### Requirement: Productized cross-board interface output
BoardApplicationService SHALL aggregate board output, cards, quality summary, subscription payload, and improvement recommendations for all primary boards without exposing workflow executor internals.

#### Scenario: Productized cross-board output stays at service boundary
- **WHEN** a caller requests productized cross-board output
- **THEN** the service returns business DTO dictionaries and does not access workflow executor internals or concrete storage
