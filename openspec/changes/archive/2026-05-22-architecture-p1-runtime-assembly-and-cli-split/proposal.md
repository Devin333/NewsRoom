## Why

Daily workflow runners and the CLI have become assembly hotspots. Splitting assembly and command groups reduces coupling while keeping existing runtime behavior intact.

## What Changes

- Add daily intelligence runtime assembly for shared connector/source setup.
- Refactor daily and agentic runners to reuse assembly while keeping constructor compatibility.
- Continue splitting CLI command groups behind the `interfaces.cli.news` facade.
- Split daily artifact publishing internals behind the existing publisher class.
- Document gate naming boundaries without renaming public types.

## Capabilities

### New Capabilities
- `runtime-assembly-governance`: Shared rules for workflow runner assembly, CLI command module ownership, artifact publisher internals, and gate naming boundaries.

### Modified Capabilities
- `business-cross-board-intelligence`: Daily and agentic workflow construction remains behavior-compatible while assembly internals are shared.
- `interfaces-contracts`: CLI commands remain compatible while command implementation modules are split further.

## Impact

- Affects daily intelligence runner internals, CLI module organization, artifact publisher internals, docs/tests.
- No manifest key, output schema, profile, or quality decision changes.
