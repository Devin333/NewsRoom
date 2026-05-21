## ADDED Requirements

### Requirement: Classified Framework Scoring Packages
The framework scoring runtime SHALL provide classified subpackages for core contracts, features, recipes, gates, algorithms, ranking, fusion, calibration, explanation, registry, runtime, and adapters.

#### Scenario: Classified imports work
- **WHEN** callers import stable objects from v2 classified paths
- **THEN** the imports MUST resolve without requiring business modules

#### Scenario: Compatibility imports remain
- **WHEN** callers import the v1 top-level scoring modules
- **THEN** those imports MUST continue to expose the same public names

### Requirement: V2 Scoring API Additions
The framework scoring runtime SHALL expose v2 helper APIs for score mutation, context recipe binding, result updates, recipe loading, static feature providers, clamp normalization, dict adapters, and scoring errors.

#### Scenario: Helper APIs are available
- **WHEN** tests call the v2 helper methods and utility functions
- **THEN** the framework MUST return the expected immutable scoring objects or converted values

### Requirement: Algorithm And Registry Extensions
The framework scoring registry SHALL support algorithm naming, normalizer registration, and default gate specs while preserving v1 scorer accessors.

#### Scenario: Registry describes v2 extension points
- **WHEN** the default registry is built
- **THEN** it MUST describe algorithms, normalizers, and gate specs in addition to rankers, fusions, calibrators, and explainers

### Requirement: Business Scoring Migration Layer
The business layer SHALL provide a `business/scoring` migration package for board-card adapters, board feature builders, board recipes, cross-board path feature adaptation, and a lightweight board scoring service.

#### Scenario: Business scoring does not replace board workflows
- **WHEN** business scoring helpers are imported and used in tests
- **THEN** existing board tests MUST continue to pass without changing current board workflow behavior
