from __future__ import annotations

from business.boards.cross_board.graph_models import CrossBoardGraphQualitySummary, CrossBoardPath
from business.foundation import BusinessQualityCheck, quality_snapshot_from_checks


class CrossBoardGraphQualityEvaluator:
    def evaluate(self, paths: list[CrossBoardPath]) -> CrossBoardGraphQualitySummary:
        checks: list[BusinessQualityCheck] = [
            BusinessQualityCheck.create(
                "cross_board_graph_has_paths",
                passed=bool(paths),
                severity="warning",
                reason="Cross-board graph should produce at least one path.",
                observed={"path_count": len(paths)},
            ),
            BusinessQualityCheck.create(
                "cross_board_paths_have_evidence",
                passed=all(path.evidence_relation_ids for path in paths),
                severity="block",
                reason="Cross-board paths must carry evidence relation ids.",
                observed={"path_count": len(paths)},
            ),
        ]
        blocked_count = sum(1 for path in paths if path.blocking_reasons)
        warnings = sum(len(path.guard_result.warnings) for path in paths if path.guard_result is not None)
        snapshot = quality_snapshot_from_checks(checks, score=1.0 if all(check.passed for check in checks) else 0.5, confidence=0.8)
        return CrossBoardGraphQualitySummary(
            status=snapshot.status,
            path_count=len(paths),
            blocked_path_count=blocked_count,
            warning_count=warnings,
            checks=checks,
            metadata={"quality_snapshot": snapshot.to_dict()},
        )


__all__ = ["CrossBoardGraphQualityEvaluator"]
