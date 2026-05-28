from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ASSET_BACKED_TYPES = {"figure", "table"}
NON_BODY_AI_MARKERS = (
    "ai summary",
    "method signal",
    "experiment signal",
    "benchmark signal",
    "recommendation",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a compiled Paper Visual Compiler artifact directory.")
    parser.add_argument("paper_dir", type=Path)
    args = parser.parse_args()

    paper_dir = args.paper_dir
    errors: list[str] = []
    warnings: list[str] = []

    document = _read_json(paper_dir / "document.json", errors)
    manifest = _read_json(paper_dir / "manifest.json", errors)
    status = _read_json(paper_dir / "status.json", errors)
    if not isinstance(document, dict) or not isinstance(manifest, dict):
        _report(errors, warnings)
        return 1

    if isinstance(status, dict) and status.get("status") != "compiled":
        errors.append(f"status is not compiled: {status.get('status')}")
    if document.get("status") != "compiled":
        errors.append(f"document status is not compiled: {document.get('status')}")

    assets = {
        str(asset.get("assetId")): asset
        for asset in manifest.get("assets", [])
        if isinstance(asset, dict) and asset.get("assetId")
    }
    visual_labels: list[str] = []

    for block in document.get("blocks", []):
        if not isinstance(block, dict):
            errors.append("document contains a non-object block")
            continue
        block_type = str(block.get("type") or "")
        text = str(block.get("text") or "")
        block_id = str(block.get("id") or "<missing-id>")
        lowered = text.casefold()
        if any(marker in lowered for marker in NON_BODY_AI_MARKERS):
            warnings.append(f"possible AI marker in body block {block_id}")

        if block_type in ASSET_BACKED_TYPES:
            visual_labels.append(str(block.get("label") or ""))
            asset_id = block.get("assetId")
            if not asset_id:
                errors.append(f"{block_type} block {block_id} has no assetId")
                continue
            asset = assets.get(str(asset_id))
            if not asset:
                errors.append(f"{block_type} block {block_id} references missing asset {asset_id}")
                continue
            _validate_asset_file(paper_dir, asset, block_id, errors)
            for key in ("label", "caption", "source"):
                if not asset.get(key):
                    errors.append(f"asset {asset_id} for block {block_id} missing {key}")

        if block_type == "equation":
            if block.get("assetId"):
                errors.append(f"equation block {block_id} must not have assetId")
            if not block.get("source"):
                errors.append(f"equation block {block_id} missing source")
            if not _looks_like_equation(text):
                errors.append(f"equation block {block_id} does not look like standalone formula text")

    repeated = {label: count for label, count in Counter(label for label in visual_labels if label).items() if count > 3}
    if repeated:
        errors.append(f"visual labels appear over-segmented: {repeated}")

    _report(errors, warnings)
    return 1 if errors else 0


def _read_json(path: Path, errors: list[str]) -> Any:
    if not path.exists():
        errors.append(f"missing file: {path}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"invalid JSON {path}: {exc}")
        return None


def _validate_asset_file(paper_dir: Path, asset: dict[str, Any], block_id: str, errors: list[str]) -> None:
    file_name = str(asset.get("fileName") or "")
    if not file_name:
        errors.append(f"asset for block {block_id} missing fileName")
        return
    path = (paper_dir / file_name).resolve()
    root = paper_dir.resolve()
    if root != path and root not in path.parents:
        errors.append(f"asset for block {block_id} escapes paper dir: {file_name}")
        return
    if not path.exists():
        errors.append(f"asset file for block {block_id} does not exist: {file_name}")
    if int(asset.get("width") or 0) <= 0 or int(asset.get("height") or 0) <= 0:
        errors.append(f"asset for block {block_id} has invalid dimensions")
    if not asset.get("checksum"):
        errors.append(f"asset for block {block_id} missing checksum")


def _looks_like_equation(text: str) -> bool:
    compact = " ".join(text.split())
    if not compact:
        return False
    if "\\" in compact:
        return True
    math_chars = sum(1 for char in compact if char in "=+-*/^_(){}[]|,.;:<>≤≥∑∫√")
    words = [part for part in compact.replace("_", " ").split() if part.isalpha()]
    if "=" not in compact and math_chars < 4:
        return False
    if len(words) > 18 and math_chars < max(5, len(words) // 2):
        return False
    return True


def _report(errors: list[str], warnings: list[str]) -> None:
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    if not errors:
        print("Paper document artifact passed guardrail checks.")


if __name__ == "__main__":
    raise SystemExit(main())
