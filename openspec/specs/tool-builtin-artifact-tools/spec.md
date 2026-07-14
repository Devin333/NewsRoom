# tool-builtin-artifact-tools Specification

## Purpose
TBD - created by archiving change tool-builtin-artifact-tools. Update Purpose after archive.
## Requirements
### Requirement: Built-in artifact tools use real artifact files
The system SHALL provide built-in artifact tools that read and write files under
the current run artifact directory.

#### Scenario: Write then load JSON artifact
- **WHEN** `artifact.write` writes JSON content and `artifact.load` reads the same path
- **THEN** the loaded content matches the written content

### Requirement: Artifact tools prevent path traversal
The system SHALL reject absolute paths and parent-directory traversal for
artifact tool paths.

#### Scenario: Parent path is rejected
- **WHEN** `artifact.load` is called with a path containing `..`
- **THEN** ToolExecutor returns a failed result
