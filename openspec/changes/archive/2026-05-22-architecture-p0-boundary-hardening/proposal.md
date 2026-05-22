## Why

Framework runtime quality work now depends on clear architecture boundaries. A few low-risk boundary leaks and oversized compatibility surfaces should be hardened before larger refactors.

## What Changes

- Remove the `framework.specs` dependency on workflow runtime status classification.
- Add architecture tests for Skill Runtime ownership and import boundaries.
- Split the first low-risk CLI command groups while preserving `interfaces.cli.news` compatibility.
- Make the known infrastructure-to-business memory dependency explicit as tracked architecture debt.

## Capabilities

### New Capabilities
- `architecture-boundary-governance`: Boundary rules for framework specs, Skill Runtime ownership, CLI compatibility, and tracked infrastructure dependency debt.

### Modified Capabilities
- `interfaces-contracts`: CLI entrypoint compatibility is preserved while command implementations may move behind the facade.

## Impact

- Affects `framework/specs`, `framework/skills`, `interfaces/cli`, architecture tests, and OpenSpec change records.
- No public API break, workflow behavior change, or business semantic change.
