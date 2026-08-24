from __future__ import annotations

from interfaces.api import create_app


def test_api_router_parity_keeps_current_paths_registered() -> None:
    app = create_app(audit_emitter_factory=None)
    paths = {route.path for route in app.routes}

    expected_paths = {
        "/health",
        "/health/live",
        "/health/ready",
        "/health/dependencies",
        "/api/v2/graph-runs",
        "/api/v2/graph-runs/catalog/health",
        "/api/v2/graph-runs/compare",
        "/api/v2/graph-runs/{run_id}",
        "/api/v2/graph-runs/{run_id}/manifest",
        "/api/v2/graph-runs/{run_id}/events",
        "/api/v2/graph-runs/{run_id}/steps",
        "/api/v2/graph-runs/{run_id}/events/stream",
        "/api/v2/graph-runs/{run_id}/replay",
        "/api/v2/graph-runs/{run_id}/diagnostics",
        "/api/v2/graph-runs/{run_id}/health",
        "/api/v2/graph-runs/{run_id}/lineage",
        "/api/v2/graph-runs/{run_id}/lineage/upstream",
        "/api/v2/graph-runs/{run_id}/lineage/downstream",
        "/api/v2/graph-runs/{run_id}/artifacts",
        "/api/v2/graph-runs/{run_id}/artifacts/{artifact_key}",
        "/api/v2/graph-runs/{run_id}/cancel",
        "/api/v2/graph-runs/{run_id}/waits/{node_instance_id}",
        "/api/v2/graph-runs/{run_id}/waits/{node_instance_id}/signals",
        "/api/v2/graph-runs/{run_id}/waits/{node_instance_id}/approval",
        "/api/v2/graph-runs/{run_id}/waits/{node_instance_id}/cancel",
        "/api/v1/reports/latest",
        "/api/v1/reports",
        "/api/v1/reports/{report_id}",
        "/api/v1/reports/{report_id}/markdown",
        "/api/v1/reports/{report_id}/quality",
        "/api/v1/reports/{report_id}/request-review",
        "/api/v1/reports/{report_id}/publish",
        "/api/v1/search/reports",
        "/api/v1/memory/search",
        "/api/v1/memory/reindex",
        "/api/v1/memory/{document_id}",
        "/api/v1/sources",
        "/api/v1/sources/health",
        "/api/v1/sources/validation",
        "/api/v1/sources/categories",
        "/api/v1/sources/priorities",
        "/api/v1/sources/{source_id}",
        "/api/v1/sources/{source_id}/probe",
        "/api/v1/sources/fetch",
        "/api/v1/sources/fetch-category",
        "/api/v1/sources/fetch-priority",
        "/api/v1/sources/fetch-topic",
        "/api/v1/sources/arxiv/fetch",
        "/api/v1/sources/github/releases",
        "/api/v1/research/papers/analyze",
        "/api/v1/research/papers/{paper_id}/analysis",
        "/api/v1/research/papers/{paper_id}/reader",
        "/api/v1/research/papers/{paper_id}/ask",
        "/api/v1/research/runs/{run_id}/trace",
        "/api/v1/workers",
        "/api/v1/workers/{worker_id}",
        "/api/v1/queues",
        "/api/v1/storage/metrics",
        "/api/v1/storage/retention/plan",
        "/api/v1/mcp/catalog",
        "/api/v1/mcp/capabilities",
        "/api/v1/mcp/manifest",
        "/api/v1/schedules",
        "/api/v1/schedules/tick",
        "/api/v1/schedules/{schedule_id}/trigger",
        "/api/v1/entities",
        "/api/v1/entities/{entity_id}/enable",
        "/api/v1/entities/{entity_id}/disable",
        "/api/v1/entities/{entity_id}",
        "/api/v1/entities/{entity_id}/report-matches",
        "/api/v1/subscriptions",
        "/api/v1/subscriptions/{subscription_id}/enable",
        "/api/v1/subscriptions/{subscription_id}/disable",
        "/api/v1/subscriptions/{subscription_id}",
        "/api/v1/admin/diagnose",
    }

    assert expected_paths <= paths
    assert not any(path.startswith("/api/v1/papers") for path in paths)
    assert not any(path.startswith("/api/v1/boards") for path in paths)
    assert "/api/v2/graph-runs/daily" not in paths
    assert "/api/v2/graph-runs/weekly" not in paths
    assert "/api/v1/approvals/{approval_id}/resume-workflow" not in paths
    assert not any(path.startswith("/api/v1/approvals") for path in paths)
    assert "/api/v1/schedules/daily" not in paths
    assert "/api/v1/schedules/papers/ingest" not in paths
