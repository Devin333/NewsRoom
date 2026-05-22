# architecture-boundary-governance Specification

## Purpose
TBD - created by archiving change architecture-p0-boundary-hardening. Update Purpose after archive.
## Requirements
### Requirement: Framework specs do not depend on workflow runtime
The system SHALL keep framework specification models free of imports from workflow runtime modules.

#### Scenario: Status terminal checks
- **WHEN** callers evaluate step or workflow terminal status from `framework.specs`
- **THEN** the result is computed without importing `framework.workflow.runtime`

### Requirement: Skill Runtime ownership is explicit
The system SHALL keep Skill Runtime implementation under `framework.skills` and prevent business, infrastructure, or interface imports from entering that package.

#### Scenario: Skill Runtime boundary test
- **WHEN** architecture boundary tests inspect Skill Runtime imports
- **THEN** forbidden layer imports are reported as failures

### Requirement: Infrastructure memory dependency debt is tracked
The system SHALL explicitly list current infrastructure modules that depend on business memory models until a port/DTO migration removes them.

#### Scenario: Known debt visibility
- **WHEN** architecture tests inspect infrastructure memory and graph modules
- **THEN** only listed legacy dependency paths are allowed
