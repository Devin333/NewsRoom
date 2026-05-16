from __future__ import annotations

from pathlib import Path


def test_parallel_join_subworkflow_contract_files_are_present() -> None:
    test_dir = Path(__file__).parent

    expected_files = [
        "test_parallel_group_contract.py",
        "test_parallel_group_observability.py",
        "test_join_contract.py",
        "test_subworkflow.py",
        "test_subworkflow_manifest_links.py",
    ]

    assert [name for name in expected_files if not (test_dir / name).exists()] == []
