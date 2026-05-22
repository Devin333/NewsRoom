## ADDED Requirements

### Requirement: CLI entrypoint remains compatible
The system SHALL preserve the public `interfaces.cli.news` command entrypoint while allowing command implementation modules to be split internally.

#### Scenario: Existing callers use news main
- **WHEN** callers invoke `interfaces.cli.news.main` with existing arguments
- **THEN** the command behavior and output format remain compatible

#### Scenario: Existing parser construction
- **WHEN** callers import and invoke `interfaces.cli.news.build_parser`
- **THEN** the returned parser supports existing commands and options
