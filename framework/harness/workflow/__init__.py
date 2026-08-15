"""Legacy Workflow declaration and transitional compiler surface."""

from framework.harness.workflow.compiler import (
    HarnessGraphCompileResult,
    HarnessWorkflowGraphCompiler,
)
from framework.harness.workflow.graph import (
    HarnessBranch,
    HarnessCompensationReference,
    HarnessContractKind,
    HarnessContractReference,
    HarnessControlNode,
    HarnessExecutableNode,
    HarnessGraphChecksumRegistry,
    HarnessGraphEdge,
    HarnessGraphEdgeKind,
    HarnessGraphNode,
    HarnessGraphNodeKind,
    HarnessJoinContract,
    HarnessLoopContract,
    HarnessMergeContract,
    HarnessMergeKind,
    HarnessWaitContract,
    NormalizedHarnessGraph,
    graph_node_from_dict,
)
from framework.harness.workflow.reader import HarnessWorkflowContractReader
from framework.harness.workflow.spec import (
    HarnessRouteKind,
    HarnessRoutingRule,
    HarnessWorkflowSpec,
)
from framework.harness.workflow.versioning import (
    DEFAULT_HARNESS_GRAPH_SCHEMA_REGISTRY,
    HarnessGraphSchemaRegistry,
)
from framework.harness.workflow.validation import (
    HarnessGraphDiagnostic,
    HarnessGraphPreflight,
    HarnessGraphPreflightPolicy,
    HarnessGraphRegistrySnapshot,
    HarnessGraphValidationPhase,
    HarnessGraphValidationResult,
    HarnessPreparedGraph,
    graph_contract_references,
)

__all__ = [
    "DEFAULT_HARNESS_GRAPH_SCHEMA_REGISTRY",
    "HarnessBranch",
    "HarnessCompensationReference",
    "HarnessContractKind",
    "HarnessContractReference",
    "HarnessControlNode",
    "HarnessExecutableNode",
    "HarnessGraphChecksumRegistry",
    "HarnessGraphCompileResult",
    "HarnessGraphDiagnostic",
    "HarnessGraphEdge",
    "HarnessGraphEdgeKind",
    "HarnessGraphNode",
    "HarnessGraphNodeKind",
    "HarnessGraphPreflight",
    "HarnessGraphPreflightPolicy",
    "HarnessGraphRegistrySnapshot",
    "HarnessGraphSchemaRegistry",
    "HarnessGraphValidationPhase",
    "HarnessGraphValidationResult",
    "HarnessJoinContract",
    "HarnessLoopContract",
    "HarnessMergeContract",
    "HarnessMergeKind",
    "HarnessPreparedGraph",
    "HarnessRouteKind",
    "HarnessRoutingRule",
    "HarnessWaitContract",
    "HarnessWorkflowContractReader",
    "HarnessWorkflowGraphCompiler",
    "HarnessWorkflowSpec",
    "NormalizedHarnessGraph",
    "graph_contract_references",
    "graph_node_from_dict",
]
