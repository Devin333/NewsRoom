from __future__ import annotations

import json
from pathlib import Path


_INVENTORY = Path("tests/architecture/fixtures/harness_graph_caller_inventory.json")


def test_harness_graph_caller_inventory_is_complete_unique_and_classified() -> None:
    inventory = json.loads(_INVENTORY.read_text(encoding="utf-8"))
    symbols = tuple(inventory["search_symbols"])
    discovered: set[str] = set()
    for root_text in inventory["search_roots"]:
        root = Path(root_text)
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if any(symbol in text for symbol in symbols):
                discovered.add(path.as_posix())

    phase_paths = [
        path
        for paths in inventory["migration_phases"].values()
        for path in paths
    ]
    excluded_paths = list(inventory["excluded_non_harness_callers"]["paths"])
    self_exclusions = list(inventory["audit_self_exclusions"])
    classified = phase_paths + excluded_paths + self_exclusions

    assert len(classified) == len(set(classified))
    assert discovered == set(classified)
    assert all(Path(path).is_file() for path in classified)
    assert set(inventory["migration_phases"]) == {
        "A_contract_foundation",
        "B_scheduler_and_sequence_choice_cutover",
        "C_durable_state_checkpoint_and_replay",
        "D_research_adoption",
        "E_graph_inspection_and_public_projection",
    }
