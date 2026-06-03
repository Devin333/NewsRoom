from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_run_inspection_uses_dedicated_daily_output_projection() -> None:
    service_path = PROJECT_ROOT / "interfaces" / "services" / "run_inspection_service.py"
    service_source = service_path.read_text(encoding="utf-8")

    assert "project_daily_output_for_run_inspection" in service_source
    assert "project_daily_output_for_legacy_consumers" not in service_source
