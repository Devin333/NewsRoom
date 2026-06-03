from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_run_inspection_uses_dedicated_daily_output_projection() -> None:
    service_path = PROJECT_ROOT / "interfaces" / "services" / "run_inspection_service.py"
    service_source = service_path.read_text(encoding="utf-8")

    assert "project_daily_output_for_run_inspection" in service_source
    assert "project_daily_output_for_legacy_consumers" not in service_source


def test_agent_loop_input_canonicalizer_uses_alias_projection_helper() -> None:
    integration_path = (
        PROJECT_ROOT
        / "business"
        / "boards"
        / "cross_board"
        / "workflows"
        / "daily_intelligence"
        / "agent_loop_integration.py"
    )
    integration_source = integration_path.read_text(encoding="utf-8")

    assert "canonicalize_namespaced_input_aliases" in integration_source
    assert "DAILY_BUFFER_ALIASES" not in integration_source


def test_daily_alias_reverse_lookup_stays_in_buffer_alias_module() -> None:
    daily_root = (
        PROJECT_ROOT
        / "business"
        / "boards"
        / "cross_board"
        / "workflows"
        / "daily_intelligence"
    )
    buffer_access_source = (daily_root / "workflow_buffer_access.py").read_text(encoding="utf-8")
    output_projection_source = (daily_root / "output_projection.py").read_text(encoding="utf-8")

    assert "_DAILY_BUFFER_LEGACY_ALIASES" not in buffer_access_source
    assert "_DAILY_OUTPUT_LEGACY_ALIASES" not in output_projection_source
    assert "namespaced_first_key_candidates" in buffer_access_source
    assert "legacy_key_for" in output_projection_source
