from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from framework.llm.structured_output import (
    ProviderStructuredOutputRelease,
    StructuredOutputEvaluationError,
    load_structured_output_evaluation_suite,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        report = load_structured_output_evaluation_suite(
            args.schema_corpus,
            args.observations,
        ).evaluate()
        payload = report.to_dict()
        if args.release_record is not None:
            release = _load_release(args.release_record)
            issues = _release_report_issues(release, payload)
            payload["release_verification"] = {
                "release_id": release.release_id,
                "record_digest": release.digest,
                "passed": not issues,
                "issues": issues,
            }
        else:
            issues = []
    except (OSError, ValueError, StructuredOutputEvaluationError) as exc:
        parser.error(str(exc))
    encoded = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)
    return 0 if report.promotion_eligible and not issues else 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Replay structured-output provider observations through the canonical "
            "local gate and deterministic promotion thresholds."
        )
    )
    parser.add_argument("--schema-corpus", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--release-record", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def _load_release(path: Path) -> ProviderStructuredOutputRelease:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("provider release record root must be an object")
    return ProviderStructuredOutputRelease.from_dict(payload)


def _release_report_issues(
    release: ProviderStructuredOutputRelease,
    report: dict,
) -> list[str]:
    checks = {
        "provider": release.provider,
        "deployment": release.deployment,
        "capability_revision": release.capability_revision,
        "corpus_revision": release.corpus_revision,
        "corpus_digest": release.corpus_digest,
        "observation_revision": release.observation_revision,
        "observation_digest": release.observation_digest,
        "baseline_digest": release.baseline_digest,
        "evaluation_report_digest": release.evaluation_report_digest,
    }
    issues = [
        f"release_{field}_mismatch"
        for field, expected in checks.items()
        if report.get("report_digest" if field == "evaluation_report_digest" else field)
        != expected
    ]
    if release.evaluation_passed != bool(report.get("promotion_eligible")):
        issues.append("release_evaluation_disposition_mismatch")
    if report.get("projection_mode") not in release.approved_modes:
        issues.append("release_projection_mode_mismatch")
    return issues


if __name__ == "__main__":
    raise SystemExit(main())
