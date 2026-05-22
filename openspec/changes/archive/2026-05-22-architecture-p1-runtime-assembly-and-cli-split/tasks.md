## 1. Runtime Assembly

- [x] 1.1 Add daily runtime assembly module with shared source setup.
- [x] 1.2 Refactor daily and agentic runners to use shared assembly while preserving attributes and constructor arguments.

## 2. CLI And Artifact Split

- [x] 2.1 Move remaining CLI command groups into command modules behind the facade.
- [x] 2.2 Split daily artifact publisher internals behind the stable publisher class.
- [x] 2.3 Document gate result ownership boundaries.

## 3. Validation

- [x] 3.1 Run business workflow, interface CLI/service, and framework workflow/governance/scoring/skills tests.
- [x] 3.2 Validate `architecture-p1-runtime-assembly-and-cli-split` with OpenSpec strict mode.
