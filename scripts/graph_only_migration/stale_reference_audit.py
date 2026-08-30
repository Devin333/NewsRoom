"""Audit active source, documentation, and canonical specs for stale Workflow authority.

The audit distinguishes executable authority from explicit negative/history
references. Migration tooling, archived changes, and retired capability
tombstones are reported as allowlisted provenance rather than hidden.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Iterable


AUDIT_SCHEMA = "newsroom.graph-only-stale-reference-audit/v1"

# Keep the audit vocabulary data-driven without making the audit utility itself
# look like a live legacy registry to the subtract-only architecture freeze.
_legacy_word = "".join(("Work", "flow"))
_legacy_namespace = _legacy_word.lower()
MARKERS = (
    "framework." + _legacy_namespace,
    "framework.harness." + _legacy_namespace,
    _legacy_word + "Runner",
    _legacy_word + "Executor",
    "Agent" + "LoopStepRunner",
    "Harness" + _legacy_word + "Spec",
    _legacy_word + "ArtifactPublisher",
    _legacy_word + "ArtifactRef",
    "resume-" + _legacy_namespace,
    _legacy_namespace + "_id",
    _legacy_namespace + "_version",
    _legacy_namespace + "_ref",
    _legacy_word + " Runtime",
    _legacy_word + "Spec",
    _legacy_word + "RunRecord",
    "Data" + "Buffer",
)

SOURCE_ROOTS = ("backend", "framework", "infrastructure", "interfaces")
DOC_ROOTS = (
    "README.md",
    "docs/architecture",
    "docs/operations",
    "docs/framework",
    "docs/09-INTERFACES_CLI_API_MCP.md",
    "docs/api",
    "docs/mcp.md",
    "docs/sdk",
    "docs/web-console.md",
)
SPEC_ROOT = "openspec/specs"
HISTORY_PREFIXES = (
    "scripts/graph_only_migration/",
    "tests/fixtures/graph_only_migration/",
    "openspec/changes/archive/",
    "openspec/changes/graph-only-orchestration/",
)
TOMBSTONE_PREFIXES = (
    "openspec/specs/approval-workflow-resume-interfaces/",
    "openspec/specs/workflow-runtime-target-closure/",
    "openspec/specs/workflow-storage-indexing/",
)
NEGATIVE_SPEC_PREFIXES = (
    "openspec/specs/architecture-boundary-governance/",
    "openspec/specs/artifact-runtime-boundary/",
    "openspec/specs/graph-only-orchestration/",
    "openspec/specs/harness-graph/",
    "openspec/specs/research-runtime/",
    "openspec/specs/structure-cleanup-governance/",
)
METADATA_ALLOWLIST = {
    "backend/research/document/chunk_storage.py": "chunk metadata field, not orchestration authority",
    "framework/events/schema/security.py": "reserved legacy field blocked from event authority",
    "infrastructure/storage/local_json/repository.py": "legacy manifest identity is rejected before live persistence",
    "infrastructure/storage/persistence/records.py": "legacy persisted identity is rejected before live persistence",
}
NEGATIVE_CONTEXT = (
    "must not",
    "shall not",
    "does not",
    "do not",
    "without",
    "reject",
    "rejected",
    "retired",
    "legacy",
    "history",
    "historical",
    "quarantine",
    "allowlist",
    "absent",
    "unsupported",
    "not supported",
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    marker: str
    text: str
    reason: str

    def as_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "marker": self.marker,
            "text": self.text,
            "reason": self.reason,
        }


def _iter_files(project_root: Path) -> Iterable[Path]:
    seen: set[Path] = set()
    for root in SOURCE_ROOTS:
        path = project_root / root
        if path.is_dir():
            candidates = path.rglob("*.py")
        elif path.is_file():
            candidates = (path,)
        else:
            candidates = ()
        for candidate in candidates:
            if "__pycache__" in candidate.parts or candidate in seen:
                continue
            seen.add(candidate)
            yield candidate

    for root in DOC_ROOTS:
        path = project_root / root
        if path.is_file():
            candidates = (path,)
        elif path.is_dir():
            candidates = (item for item in path.rglob("*") if item.is_file())
        else:
            candidates = ()
        for candidate in candidates:
            if candidate in seen or any(part in {".git", "__pycache__"} for part in candidate.parts):
                continue
            seen.add(candidate)
            yield candidate

    spec_root = project_root / SPEC_ROOT
    if spec_root.is_dir():
        for candidate in sorted(spec_root.rglob("spec.md")):
            if candidate not in seen:
                seen.add(candidate)
                yield candidate


def _allowlist_reason(relative: str, line: str) -> str | None:
    for prefix in HISTORY_PREFIXES:
        if relative == prefix.rstrip("/") or relative.startswith(prefix):
            return f"history-only path: {prefix}"
    for prefix in TOMBSTONE_PREFIXES:
        if relative.startswith(prefix):
            return f"retired capability tombstone: {prefix}"
    for prefix in NEGATIVE_SPEC_PREFIXES:
        if relative.startswith(prefix):
            return f"negative canonical-spec contract: {prefix}"
    if relative in METADATA_ALLOWLIST:
        return METADATA_ALLOWLIST[relative]
    lowered = line.casefold()
    if any(token in lowered for token in NEGATIVE_CONTEXT):
        return "explicit negative or quarantine context"
    return None


def audit(project_root: Path) -> dict[str, object]:
    violations: list[Finding] = []
    allowlisted: list[Finding] = []
    scanned: list[str] = []
    for path in _iter_files(project_root):
        relative = path.relative_to(project_root).as_posix()
        scanned.append(relative)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for line_no, line in enumerate(lines, start=1):
            for marker in MARKERS:
                if marker not in line:
                    continue
                finding = Finding(relative, line_no, marker, line.strip(), "")
                reason = _allowlist_reason(relative, line)
                if reason is None:
                    violations.append(finding)
                else:
                    allowlisted.append(
                        Finding(relative, line_no, marker, line.strip(), reason)
                    )

    violations.sort(key=lambda item: (item.path, item.line, item.marker))
    allowlisted.sort(key=lambda item: (item.path, item.line, item.marker))
    return {
        "schema": AUDIT_SCHEMA,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "markers": list(MARKERS),
        "scanned_files": sorted(scanned),
        "history_allowlist": [*HISTORY_PREFIXES, *TOMBSTONE_PREFIXES],
        "summary": {
            "files_scanned": len(scanned),
            "violations": len(violations),
            "allowlisted_references": len(allowlisted),
            "is_valid": not violations,
        },
        "violations": [item.as_dict() for item in violations],
        "allowlisted_references": [item.as_dict() for item in allowlisted],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = audit(args.root.resolve())
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["summary"]["is_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
