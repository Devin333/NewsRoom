## MODIFIED Requirements

### Requirement: Built-in artifact tools use real artifact files
The system SHALL provide built-in artifact tools that read and write files only at canonical descendants of the current validated run artifact directory.

#### Scenario: Write then load JSON artifact
- **WHEN** `artifact.write` writes JSON content to a valid nested path and `artifact.load` reads the same path for a valid run
- **THEN** the loaded content matches the written content

#### Scenario: Run identifier is unsafe
- **WHEN** an artifact tool is configured with an unsafe run identifier
- **THEN** ToolExecutor returns a failed result before creating or reading a file

### Requirement: Artifact tools prevent path traversal
The system SHALL reject absolute, drive-relative, UNC/device, parent-traversal, reserved-character, ADS, DOS-device, trailing-dot/space, or canonical root-escaping artifact tool paths.

#### Scenario: Parent path is rejected
- **WHEN** `artifact.load` is called with a path containing `..`
- **THEN** ToolExecutor returns a failed result without reading content outside the run directory

#### Scenario: Linked path escapes the run directory
- **WHEN** `artifact.load` resolves through a symlink or junction to a target outside the run directory
- **THEN** ToolExecutor returns a failed result without returning external content
