# Graph-only History Audit Tool

`scripts.graph_only_migration` is an offline, read-only history audit tool.
It accepts detached legacy snapshots, verifies source checksums and record
identity, and produces dry-run conversion evidence or typed quarantine. It
does not write a Graph store, checkpoint, index, memory record, artifact,
publication, queue item, or worker result.

The package is intentionally excluded from production composition. The
production import-graph gate treats any edge into this package as a failure.
The supported fixture set lives under `tests/fixtures/graph_only_migration/`
and is not a runtime data source.
