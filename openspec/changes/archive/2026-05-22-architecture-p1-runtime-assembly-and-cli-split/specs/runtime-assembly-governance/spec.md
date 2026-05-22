## ADDED Requirements

### Requirement: Daily runners share source assembly
The system SHALL construct daily source registry, connectors, dispatcher, collector, and health manager through shared assembly logic used by both daily runner variants.

#### Scenario: Constructor compatibility
- **WHEN** callers instantiate daily or agentic runners with existing constructor arguments
- **THEN** source assembly produces equivalent runtime collaborators and behavior

### Requirement: CLI command modules stay behind facade
The system SHALL allow CLI command implementations to live in command modules while keeping `interfaces.cli.news` as the public entrypoint.

#### Scenario: Command module split
- **WHEN** a CLI command is implemented in a command module
- **THEN** existing invocations through `interfaces.cli.news.main` continue to work

### Requirement: Artifact publisher facade remains stable
The system SHALL preserve the daily artifact publisher public class, publisher id, and manifest artifact keys while allowing internal helper modules.

#### Scenario: Daily artifact publishing
- **WHEN** a daily workflow completes
- **THEN** artifact publishing records the same public manifest keys as before the split

### Requirement: Gate names have explicit ownership
The system SHALL document governance, scoring, and skill gate result ownership to prevent cross-runtime misuse.

#### Scenario: Gate boundary documentation
- **WHEN** developers inspect framework gate docs or tests
- **THEN** runtime, scoring, and skill gate result types have distinct documented responsibilities
