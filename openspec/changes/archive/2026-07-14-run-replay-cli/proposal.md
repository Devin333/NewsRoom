## Why

The Interface and Storage PRDs require run replay from persisted artifacts. The CLI can inspect manifests, events, and individual artifacts, but operators still cannot load a single replay bundle for a run.

## What Changes

- Add a run replay result to `RunInspectionService`.
- Include manifest, redacted events, and redacted artifact contents from the real artifact directory.
- Add `news runs replay <run_id>` with JSON and compact text output.
- Preserve missing or unreadable artifact errors in the replay bundle instead of hiding them.

## Out Of Scope

- Re-executing workflow steps.
- Resuming from checkpoints.
- Schema migration of old replay artifacts.
- Streaming large artifacts.
