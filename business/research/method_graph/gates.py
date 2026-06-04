from __future__ import annotations

from business.research.domain.common import GateResult
from business.research.method_graph.models import MethodGraphEdge


def validate_method_edge_evidence(edge: MethodGraphEdge) -> GateResult:
    if not edge.evidence_refs:
        return GateResult.fail("MethodEvidenceLineageGate", "method graph edge requires evidence refs")
    return GateResult.pass_("MethodEvidenceLineageGate")


__all__ = ["validate_method_edge_evidence"]
