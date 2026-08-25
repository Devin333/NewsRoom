"""Explicitly offline history tooling.

This package reads detached legacy snapshots for classification and dry-run
equivalence checks only.  It is not a production migration path: no public
function here can write Graph state, resume a run, dispatch a worker, or
publish an artifact.
"""

HISTORY_ONLY = True
AUTHORITY_MODE = "typed_quarantine_only"

from scripts.graph_only_migration.contracts import (
    ConversionStatus,
    GraphNodeBinding,
    GraphReference,
    LegacyRecordKind,
    LegacySourceDescriptor,
    MigrationPlan,
    QuarantineReasonCode,
    RunGraphMapping,
    ZERO_LIVE_SIDE_EFFECT_COUNTS,
)
from scripts.graph_only_migration.planner import GraphMigrationPlanner
from scripts.graph_only_migration.reader import (
    BoundedLegacySourceReader,
    MigrationSourceReadError,
    SourceProfileRegistry,
    checksum_bytes,
)
from scripts.graph_only_migration.transformer import GraphHistoryTransformer


__all__ = [
    "BoundedLegacySourceReader",
    "ConversionStatus",
    "GraphHistoryTransformer",
    "GraphMigrationPlanner",
    "GraphNodeBinding",
    "GraphReference",
    "LegacyRecordKind",
    "LegacySourceDescriptor",
    "MigrationPlan",
    "MigrationSourceReadError",
    "QuarantineReasonCode",
    "RunGraphMapping",
    "SourceProfileRegistry",
    "ZERO_LIVE_SIDE_EFFECT_COUNTS",
    "AUTHORITY_MODE",
    "HISTORY_ONLY",
    "checksum_bytes",
]
