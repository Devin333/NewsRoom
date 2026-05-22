## ADDED Requirements

### Requirement: CLI commands remain compatible during module split
The system SHALL preserve existing CLI command names, options, exit codes, and JSON/human output formats while command handlers move into grouped modules.

#### Scenario: Existing CLI tests
- **WHEN** existing CLI tests invoke commands through `interfaces.cli.news.main`
- **THEN** all command behaviors remain compatible
