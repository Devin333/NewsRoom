from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from framework.governance.diagnostics.finding import GovernanceFinding
from framework.governance.diagnostics.health import GovernanceHealthReport


@dataclass
class GovernanceReportBuilder:
    findings: list[GovernanceFinding] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def build(self, findings: list[GovernanceFinding] | None = None) -> GovernanceHealthReport:
        actual_findings = list(findings if findings is not None else self.findings)
        return GovernanceHealthReport(
            status=_status_for_findings(actual_findings),
            findings=actual_findings,
            metadata=dict(self.metadata),
        )


def _status_for_findings(findings: list[GovernanceFinding]) -> str:
    severities = {finding.severity.casefold() for finding in findings}
    if severities & {"error", "critical"}:
        return "unhealthy"
    if severities & {"warning", "warn"}:
        return "warning"
    return "healthy"
