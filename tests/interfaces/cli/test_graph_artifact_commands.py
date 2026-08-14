from __future__ import annotations

import json
from datetime import UTC, date, datetime

import interfaces.cli.news as news_cli
from interfaces.cli.commands import graph_artifacts as graph_commands
from interfaces.composition.research_errors import ResearchConfigurationError


NOW_TEXT = "2026-08-14T09:30:00Z"
NOW = datetime(2026, 8, 14, 9, 30, tzinfo=UTC)


def test_gc_plan_uses_explicit_tenant_and_exact_json(monkeypatch, capsys) -> None:
    service = _FakeGovernanceService()
    monkeypatch.setattr(
        graph_commands,
        "build_research_graph_artifact_governance_service",
        lambda: service,
    )

    exit_code = news_cli.main(
        [
            "storage",
            "graph-artifacts",
            "gc",
            "plan",
            "--tenant-id",
            "tenant-1",
            "--now",
            NOW_TEXT,
            "--json",
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "kind": "gc_plan",
        "tenant_id": "tenant-1",
    }
    assert service.calls == [
        ("plan_gc", {"tenant_id": "tenant-1", "observed_at": NOW})
    ]


def test_gc_apply_requires_yes_without_building_service(monkeypatch, capsys) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        graph_commands,
        "build_research_graph_artifact_governance_service",
        lambda: calls.append("built"),
    )

    exit_code = news_cli.main(
        [
            "storage",
            "graph-artifacts",
            "gc",
            "apply",
            "--tenant-id",
            "tenant-1",
            "--plan-checksum",
            "sha256:" + "a" * 64,
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["error"]["code"] == "graph_artifact_gc_confirmation_required"
    assert calls == []


def test_gc_apply_passes_only_prepared_identity_and_bound(monkeypatch, capsys) -> None:
    service = _FakeGovernanceService()
    monkeypatch.setattr(
        graph_commands,
        "build_research_graph_artifact_governance_service",
        lambda: service,
    )
    plan_checksum = "sha256:" + "b" * 64

    exit_code = news_cli.main(
        [
            "storage",
            "graph-artifacts",
            "gc",
            "apply",
            "--tenant-id",
            "tenant-apply",
            "--plan-checksum",
            plan_checksum,
            "--max-operations",
            "7",
            "--yes",
            "--json",
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "gc_apply"
    assert service.calls == [
        (
            "apply_gc",
            {
                "tenant_id": "tenant-apply",
                "plan_checksum": plan_checksum,
                "confirmed": True,
                "max_operations": 7,
            },
        )
    ]


def test_cost_report_parses_exact_utc_day(monkeypatch, capsys) -> None:
    service = _FakeGovernanceService()
    monkeypatch.setattr(
        graph_commands,
        "build_research_graph_artifact_governance_service",
        lambda: service,
    )

    exit_code = news_cli.main(
        [
            "storage",
            "graph-artifacts",
            "cost",
            "report",
            "--tenant-id",
            "tenant-cost",
            "--day",
            "2026-08-13",
            "--now",
            NOW_TEXT,
            "--json",
        ]
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "cost_report"
    assert service.calls == [
        (
            "generate_cost_report",
            {
                "tenant_id": "tenant-cost",
                "day": date(2026, 8, 13),
                "generated_at": NOW,
            },
        )
    ]


def test_quota_and_reconcile_use_tenant_scoped_service(monkeypatch, capsys) -> None:
    service = _FakeGovernanceService()
    monkeypatch.setattr(
        graph_commands,
        "build_research_graph_artifact_governance_service",
        lambda: service,
    )

    quota_exit = news_cli.main(
        [
            "storage",
            "graph-artifacts",
            "quota",
            "--tenant-id",
            "tenant-query",
            "--now",
            NOW_TEXT,
            "--json",
        ]
    )
    quota_payload = json.loads(capsys.readouterr().out)
    reconcile_exit = news_cli.main(
        [
            "storage",
            "graph-artifacts",
            "reconcile",
            "--tenant-id",
            "tenant-query",
            "--now",
            NOW_TEXT,
            "--json",
        ]
    )
    reconcile_payload = json.loads(capsys.readouterr().out)

    assert quota_exit == reconcile_exit == 0
    assert quota_payload["kind"] == "quota"
    assert reconcile_payload["kind"] == "reconcile"
    assert service.calls == [
        ("inspect_quota", {"tenant_id": "tenant-query", "captured_at": NOW}),
        ("reconcile", {"tenant_id": "tenant-query", "observed_at": NOW}),
    ]


def test_alert_list_and_acknowledgement_preserve_cas_fields(monkeypatch, capsys) -> None:
    service = _FakeGovernanceService()
    monkeypatch.setattr(
        graph_commands,
        "build_research_graph_artifact_governance_service",
        lambda: service,
    )
    alert_id = "graph-artifact-alert://" + "c" * 64
    checksum = "sha256:" + "d" * 64

    list_exit = news_cli.main(
        [
            "storage",
            "graph-artifacts",
            "alerts",
            "list",
            "--tenant-id",
            "tenant-alert",
            "--status",
            "open",
            "--json",
        ]
    )
    list_payload = json.loads(capsys.readouterr().out)
    ack_exit = news_cli.main(
        [
            "storage",
            "graph-artifacts",
            "alerts",
            "acknowledge",
            "--tenant-id",
            "tenant-alert",
            "--alert-id",
            alert_id,
            "--expected-checksum",
            checksum,
            "--acknowledged-by",
            "operator-1",
            "--now",
            NOW_TEXT,
            "--json",
        ]
    )
    ack_payload = json.loads(capsys.readouterr().out)

    assert list_exit == ack_exit == 0
    assert list_payload["kind"] == "alert_list"
    assert ack_payload["kind"] == "alert_acknowledge"
    assert service.calls[0][0] == "list_alerts"
    assert service.calls[0][1]["status"].value == "open"
    assert service.calls[1] == (
        "acknowledge_alert",
        {
            "tenant_id": "tenant-alert",
            "alert_id": alert_id,
            "expected_checksum": checksum,
            "acknowledged_by": "operator-1",
            "acknowledged_at": NOW,
        },
    )


def test_invalid_day_returns_sanitized_exact_error(monkeypatch, capsys) -> None:
    service = _FakeGovernanceService()
    monkeypatch.setattr(
        graph_commands,
        "build_research_graph_artifact_governance_service",
        lambda: service,
    )
    invalid = "2026-08-14/private/path"

    exit_code = news_cli.main(
        [
            "storage",
            "graph-artifacts",
            "cost",
            "report",
            "--tenant-id",
            "tenant-cost",
            "--day",
            invalid,
            "--json",
        ]
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 1
    assert payload["error"]["code"] == "result_schema_invalid"
    assert invalid not in output


def test_invalid_production_settings_return_typed_unavailability(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        graph_commands,
        "build_research_graph_artifact_governance_service",
        lambda: (_ for _ in ()).throw(
            ResearchConfigurationError(("research.graph_artifact_persistence",))
        ),
    )

    exit_code = news_cli.main(
        [
            "storage",
            "graph-artifacts",
            "quota",
            "--tenant-id",
            "tenant-query",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["error"]["code"] == "research_configuration_invalid"
    assert payload["error"]["capabilities"] == [
        "research.graph_artifact_persistence"
    ]


class _FakeGovernanceService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def plan_gc(self, **kwargs):
        return self._result("gc_plan", kwargs)

    def apply_gc(self, **kwargs):
        return self._result("gc_apply", kwargs)

    def generate_cost_report(self, **kwargs):
        return self._result("cost_report", kwargs)

    def inspect_quota(self, **kwargs):
        return self._result("quota", kwargs)

    def reconcile(self, **kwargs):
        return self._result("reconcile", kwargs)

    def list_alerts(self, **kwargs):
        return self._result("alert_list", kwargs)

    def acknowledge_alert(self, **kwargs):
        return self._result("alert_acknowledge", kwargs)

    def _result(self, kind: str, values: dict):
        self.calls.append((kind if kind != "cost_report" else "generate_cost_report", values))
        method_name = {
            "gc_plan": "plan_gc",
            "gc_apply": "apply_gc",
            "quota": "inspect_quota",
            "reconcile": "reconcile",
            "alert_list": "list_alerts",
            "alert_acknowledge": "acknowledge_alert",
        }.get(kind)
        if method_name is not None:
            self.calls[-1] = (method_name, values)
        return _FakeResult({"kind": kind, "tenant_id": values["tenant_id"]})


class _FakeResult:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def to_dict(self) -> dict:
        return dict(self._payload)
