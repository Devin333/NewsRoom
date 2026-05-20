from __future__ import annotations

from framework.governance.diagnostics import (
    GovernanceFinding,
    GovernanceHealthReport,
    GovernanceReportBuilder,
)


def test_governance_finding_and_health_report_serialize() -> None:
    finding = GovernanceFinding(message="watch", severity="warning", source="policy")
    report = GovernanceHealthReport(status="warning", findings=[finding])

    data = report.to_dict()

    assert data["status"] == "warning"
    assert data["findings"][0]["message"] == "watch"


def test_governance_report_builder_derives_status_from_findings() -> None:
    assert GovernanceReportBuilder().build().status == "healthy"
    assert GovernanceReportBuilder([GovernanceFinding("warn", severity="warning")]).build().status == "warning"
    assert GovernanceReportBuilder([GovernanceFinding("bad", severity="critical")]).build().status == "unhealthy"
