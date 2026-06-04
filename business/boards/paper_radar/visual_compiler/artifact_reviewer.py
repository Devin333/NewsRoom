from __future__ import annotations

import hashlib
import html
import json
import re
import struct
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone as _tz
from enum import StrEnum
from pathlib import Path
from typing import Any


UTC = _tz.utc
REVIEWER_ID = "paper-reader-artifact-reviewer-v1"
MEMORY_SCHEMA_VERSION = "paper_reader_artifact_review_memory_v1"
VISUAL_ASSET_TYPES = {"figure", "table"}
ASSET_BACKED_BLOCK_TYPES = {"figure", "table"}
VISUAL_BLOCK_TYPES = {"figure", "table", "equation"}

_HTML_ENTITY_LEAK_PATTERN = re.compile(r"&(?:amp|lt|gt|quot|apos|nbsp);")
_MOJIBAKE_PATTERN = re.compile("\ufffd|\u951f|\u95bf|\u8133|\u8292")
_LATEX_ENV_LEAK_PATTERN = re.compile(r"\\(?:begin|end)\s*\{[^}]{1,80}\}")
_LATEX_TEXT_COMMAND_LEAK_PATTERN = re.compile(
    r"\\(?:mathrm|textrm|text|textsc|texttt|mathbf|mathcal|mathbb|mathsf|operatorname|emph|textbf|textit)\*?\s*\{"
)
_LATEX_READER_COMMAND_LEAK_PATTERN = re.compile(r"\\(?:[A-Za-z]+|[,;:!]|\\)")
_TABLE_ALIGNMENT_LEAK_PATTERN = re.compile(r"(?:^|\s)[lcr]{2,}(?:\s*&|$)|(?:^|[^&])&[^&]+&")
_CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_EMPTY_INLINE_MARKUP_PATTERN = re.compile(r"<(?:strong|b|em|i|span)(?:\s[^>]*)?>\s*</(?:strong|b|em|i|span)>", re.IGNORECASE)


class PaperArtifactReviewStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class PaperArtifactReviewTask:
    child_agent_id: str
    inputs: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperArtifactReviewResult:
    child_agent_id: str
    success: bool
    status: PaperArtifactReviewStatus
    output: Mapping[str, Any] = field(default_factory=dict)
    summary: str = ""
    error: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


class PaperReaderArtifactReviewSubAgent:
    def __init__(
        self,
        *,
        max_blank_ratio: float = 0.9985,
        min_visual_width: int = 16,
        min_visual_height: int = 16,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.max_blank_ratio = max_blank_ratio
        self.min_visual_width = min_visual_width
        self.min_visual_height = min_visual_height
        self.clock = clock or (lambda: datetime.now(UTC))

    @property
    def reviewer_id(self) -> str:
        return REVIEWER_ID

    def execute(self, task: Any) -> PaperArtifactReviewResult:
        inputs = _mapping(getattr(task, "inputs", None)) or {}
        child_agent_id = _text(getattr(task, "child_agent_id", None)) or "paper-artifact-reviewer"
        try:
            output = self.review(
                document=_mapping(inputs.get("document")) or {},
                manifest=_mapping(inputs.get("manifest")) or {},
                paper_dir=_optional_path(inputs.get("paper_dir")),
                memory_path=_optional_path(inputs.get("memory_path")),
            )
        except Exception as exc:
            return PaperArtifactReviewResult(
                child_agent_id=child_agent_id,
                success=False,
                status=PaperArtifactReviewStatus.FAILED,
                error=str(exc),
                metadata={"reviewer": self.reviewer_id},
            )
        return PaperArtifactReviewResult(
            child_agent_id=child_agent_id,
            success=bool(output.get("passed")),
            status=PaperArtifactReviewStatus.SUCCEEDED if output.get("passed") else PaperArtifactReviewStatus.FAILED,
            output=dict(output),
            summary=str(output.get("summary") or ""),
            metadata={"reviewer": self.reviewer_id},
        )

    def run(self, task: Any) -> PaperArtifactReviewResult:
        return self.execute(task)

    def review(
        self,
        *,
        document: Mapping[str, Any],
        manifest: Mapping[str, Any],
        paper_dir: Path | None = None,
        memory_path: Path | None = None,
    ) -> Mapping[str, Any]:
        paper_id = _paper_id(document, manifest)
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        image_errors, image_warnings = self._image_gate_issues(
            document=document,
            manifest=manifest,
            paper_dir=paper_dir,
            paper_id=paper_id,
        )
        table_errors, table_warnings = _table_gate_issues(document=document, manifest=manifest, paper_id=paper_id)
        equation_errors, equation_warnings = _equation_gate_issues(document=document, paper_id=paper_id)
        symbol_errors, symbol_warnings = _symbol_gate_issues(
            document=document,
            manifest=manifest,
            paper_dir=paper_dir,
            paper_id=paper_id,
        )
        errors.extend((*image_errors, *table_errors, *equation_errors, *symbol_errors))
        warnings.extend((*image_warnings, *table_warnings, *equation_warnings, *symbol_warnings))
        raw_issues = (*errors, *warnings)
        errors = _dedupe_issues(errors)
        warnings = _dedupe_issues(warnings, seen={_text(issue.get("fingerprint")) for issue in errors})

        memory_result = _review_memory_result(
            issues=raw_issues,
            paper_id=paper_id,
            memory_path=memory_path,
            now=_iso(self.clock()),
        )
        errors = [_attach_memory_match(issue, memory_result) for issue in errors]
        warnings = [_attach_memory_match(issue, memory_result) for issue in warnings]
        memory_warning = memory_result.get("warning")
        if isinstance(memory_warning, Mapping):
            warnings.append(dict(memory_warning))

        gates = _gate_summaries(errors=errors, warnings=warnings)
        return {
            "passed": not errors,
            "reviewer": self.reviewer_id,
            "summary": _summary(errors, warnings),
            "gates": gates,
            "errors": errors,
            "warnings": warnings,
            "memory": {
                "attempted": memory_result["attempted"],
                "saved": memory_result["saved"],
                "journalRef": memory_result.get("journalRef"),
                "matchCount": len(memory_result["matches"]),
                "error": memory_result.get("error"),
            },
            "memoryMatches": list(memory_result["matches"].values()),
        }

    def _image_gate_issues(
        self,
        *,
        document: Mapping[str, Any],
        manifest: Mapping[str, Any],
        paper_dir: Path | None,
        paper_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        assets = _assets(manifest)
        blocks = _blocks(document)
        assets_by_id = {_text(asset.get("assetId")): asset for asset in assets if _text(asset.get("assetId"))}

        for asset in assets:
            asset_id = _text(asset.get("assetId"))
            kind = _text(asset.get("kind"))
            width = _positive_int(asset.get("width")) or 0
            height = _positive_int(asset.get("height")) or 0
            if kind in VISUAL_ASSET_TYPES:
                if width < self.min_visual_width or height < self.min_visual_height:
                    errors.append(_issue("asset_dimensions_too_small", "visual asset is too small", gate="image", paper_id=paper_id, assetId=asset_id))
                if not _text(asset.get("label")):
                    errors.append(_issue("asset_label_missing", "visual asset label is missing", gate="image", paper_id=paper_id, assetId=asset_id))
                if not _text(asset.get("caption")):
                    errors.append(_issue("asset_caption_missing", "visual asset caption is missing", gate="image", paper_id=paper_id, assetId=asset_id))
                if not isinstance(asset.get("source"), Mapping):
                    errors.append(_issue("asset_source_missing", "visual asset source bbox is missing", gate="image", paper_id=paper_id, assetId=asset_id))
                if kind == "table" and _text(asset.get("mimeType")).startswith("text/html"):
                    metadata = _mapping(asset.get("metadata")) or {}
                    if not isinstance(metadata.get("tableModel"), Mapping) or not metadata.get("tableHtml"):
                        errors.append(_issue("table_asset_model_missing", "structured table asset is missing table model/html metadata", gate="table", paper_id=paper_id, assetId=asset_id))
                else:
                    blank_ratio = _optional_float(asset.get("blankRatio"))
                    if blank_ratio is None:
                        blank_ratio = _blank_ratio_for_asset(asset=asset, paper_dir=paper_dir)
                    if blank_ratio is not None and blank_ratio >= self.max_blank_ratio:
                        warnings.append(
                            _issue(
                                "asset_blank",
                                "visual asset is effectively blank",
                                gate="image",
                                paper_id=paper_id,
                                assetId=asset_id,
                                blankRatio=round(blank_ratio, 6),
                            )
                        )
            elif kind == "page" and not isinstance(asset.get("source"), Mapping):
                warnings.append(_issue("page_source_missing", "page asset source bbox is missing", gate="image", paper_id=paper_id, assetId=asset_id))

        for block in blocks:
            block_id = _text(block.get("id"))
            block_type = _text(block.get("type"))
            asset_id = _text(block.get("assetId"))
            if not isinstance(block.get("source"), Mapping):
                warnings.append(_issue("block_source_missing", "block source bbox is missing", gate="image", paper_id=paper_id, blockId=block_id))
            if block_type in ASSET_BACKED_BLOCK_TYPES:
                if not asset_id:
                    errors.append(_issue("visual_block_asset_missing", "visual block does not reference an asset", gate="image", paper_id=paper_id, blockId=block_id))
                    continue
                asset = assets_by_id.get(asset_id)
                if asset is None:
                    errors.append(_issue("visual_block_asset_not_found", "visual block references an asset missing from manifest", gate="image", paper_id=paper_id, blockId=block_id, assetId=asset_id))
                    continue
                asset_kind = _text(asset.get("kind"))
                if asset_kind != block_type:
                    errors.append(_issue("visual_block_asset_kind_mismatch", "visual block type does not match asset kind", gate="image", paper_id=paper_id, blockId=block_id, assetId=asset_id, blockType=block_type, assetKind=asset_kind))
                if not _text(block.get("label")):
                    errors.append(_issue("visual_block_label_missing", "visual block label is missing", gate="image", paper_id=paper_id, blockId=block_id, assetId=asset_id))
                if not _text(block.get("caption")):
                    errors.append(_issue("visual_block_caption_missing", "visual block caption is missing", gate="image", paper_id=paper_id, blockId=block_id, assetId=asset_id))
                if block_type == "table" and _text(asset.get("mimeType")).startswith("text/html"):
                    metadata = _mapping(block.get("metadata")) or {}
                    if not isinstance(metadata.get("tableModel"), Mapping) or not metadata.get("tableHtml"):
                        errors.append(_issue("table_block_model_missing", "structured table block is missing table model/html metadata", gate="table", paper_id=paper_id, blockId=block_id, assetId=asset_id))

        visual_assets = [asset for asset in assets if _text(asset.get("kind")) in VISUAL_ASSET_TYPES]
        asset_backed_blocks = [block for block in blocks if _text(block.get("type")) in ASSET_BACKED_BLOCK_TYPES]
        if visual_assets and not asset_backed_blocks:
            errors.append(_issue("visual_assets_unbound", "manifest has visual assets but document has no visual blocks", gate="image", paper_id=paper_id))
        label_counts = Counter(_text(block.get("label")) for block in asset_backed_blocks if _text(block.get("label")))
        repeated_labels = {label: count for label, count in label_counts.items() if count > 3}
        if repeated_labels:
            warnings.append(_issue("visual_block_label_repeated", "too many visual blocks share the same label; likely over-segmented PDF image crops", gate="image", paper_id=paper_id, labels=repeated_labels))
        unique_asset_labels = {_text(asset.get("label")) for asset in visual_assets if _text(asset.get("label"))}
        if len(visual_assets) > 24 and unique_asset_labels and len(visual_assets) > len(unique_asset_labels) * 3:
            warnings.append(_issue("visual_assets_oversegmented", "visual assets appear over-segmented relative to figure/table labels", gate="image", paper_id=paper_id, visualAssetCount=len(visual_assets), uniqueLabelCount=len(unique_asset_labels)))
        return errors, warnings


def _table_gate_issues(*, document: Mapping[str, Any], manifest: Mapping[str, Any], paper_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    table_asset_by_id = {_text(asset.get("assetId")): asset for asset in _assets(manifest) if _text(asset.get("kind")) == "table"}

    for block in _blocks(document):
        if _text(block.get("type")) != "table":
            continue
        block_id = _text(block.get("id"))
        asset_id = _text(block.get("assetId"))
        metadata = _mapping(block.get("metadata")) or {}
        table_model = _mapping(metadata.get("tableModel"))
        table_text = _text(metadata.get("tableText")) or _text(block.get("text")) or _text(block.get("caption"))
        table_html = _text(metadata.get("tableHtml"))
        asset = table_asset_by_id.get(asset_id)
        asset_metadata = _mapping(asset.get("metadata")) if asset is not None else None
        asset_model = _mapping(asset_metadata.get("tableModel")) if asset_metadata is not None else None

        if table_model is not None and not _table_model_has_readable_cells(table_model):
            errors.append(_issue("table_model_has_no_readable_cells", "structured table model has no readable cells", gate="table", paper_id=paper_id, blockId=block_id, assetId=asset_id))
        if asset_model is not None and not _table_model_has_readable_cells(asset_model):
            errors.append(_issue("table_asset_model_has_no_readable_cells", "structured table asset model has no readable cells", gate="table", paper_id=paper_id, blockId=block_id, assetId=_text(asset.get("assetId")) if asset is not None else asset_id))

        for chunk in (table_text, _table_model_text(table_model), _table_model_text(asset_model)):
            if _looks_like_unparsed_table_alignment(chunk):
                errors.append(_issue("table_alignment_tokens_visible", "table alignment syntax is visible in reader-facing table text", gate="table", paper_id=paper_id, blockId=block_id, assetId=asset_id, sample=_sample(chunk), surface="table.text"))
                break
        if _LATEX_ENV_LEAK_PATTERN.search(table_text):
            errors.append(_issue("table_latex_environment_visible", "raw LaTeX table environment is visible in reader-facing table text", gate="table", paper_id=paper_id, blockId=block_id, assetId=asset_id, sample=_sample(table_text), surface="metadata.tableText"))
        if table_html and _EMPTY_INLINE_MARKUP_PATTERN.search(table_html):
            warnings.append(_issue("table_empty_inline_markup", "table HTML contains empty inline formatting markup", gate="table", paper_id=paper_id, blockId=block_id, assetId=asset_id, surface="metadata.tableHtml"))
    return errors, warnings


def _equation_gate_issues(*, document: Mapping[str, Any], paper_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    for block in _blocks(document):
        block_id = _text(block.get("id"))
        block_type = _text(block.get("type"))
        metadata = _mapping(block.get("metadata")) or {}
        if block_type == "equation":
            equation_text = (_text(block.get("text")) or _text(block.get("caption")) or _text(metadata.get("equationText"))).strip()
            if _text(block.get("assetId")):
                errors.append(_issue("equation_block_asset_unexpected", "equation block must be generated as text, not an image asset", gate="equation", paper_id=paper_id, blockId=block_id, assetId=_text(block.get("assetId"))))
            if not equation_text:
                errors.append(_issue("equation_text_missing", "equation block text is missing", gate="equation", paper_id=paper_id, blockId=block_id))
            if re.search(r"\\(?:begin|end)\s*\{(?:tabular|table|figure)\}", equation_text):
                errors.append(_issue("equation_contains_non_equation_environment", "equation block contains a non-equation LaTeX environment", gate="equation", paper_id=paper_id, blockId=block_id, sample=_sample(equation_text), surface="block.text"))
            if re.search(r"\\(?:begin|end)\s*\{(?:small|scriptsize|footnotesize|tiny|large|Large)\}", equation_text):
                errors.append(_issue("equation_contains_formatting_environment", "equation block contains a TeX formatting environment instead of pure math", gate="equation", paper_id=paper_id, blockId=block_id, sample=_sample(equation_text), surface="block.text"))
            if equation_text.count("{") != equation_text.count("}"):
                warnings.append(_issue("equation_braces_unbalanced", "equation text has unbalanced braces", gate="equation", paper_id=paper_id, blockId=block_id, sample=_sample(equation_text), surface="block.text"))
            if not isinstance(block.get("source"), Mapping):
                errors.append(_issue("equation_source_missing", "equation block source bbox is missing", gate="equation", paper_id=paper_id, blockId=block_id))

        inline_spans = metadata.get("inlineSpans")
        if not isinstance(inline_spans, list):
            continue
        for index, span in enumerate(inline_spans):
            if not isinstance(span, Mapping) or span.get("type") != "math":
                continue
            latex = _text(span.get("latex"))
            text = _text(span.get("text"))
            if not latex and not text:
                errors.append(_issue("inline_equation_empty", "inline math span has neither display text nor LaTeX", gate="equation", paper_id=paper_id, blockId=block_id, spanIndex=index))
    return errors, warnings


def _symbol_gate_issues(
    *,
    document: Mapping[str, Any],
    manifest: Mapping[str, Any],
    paper_dir: Path | None,
    paper_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    native_text = _native_pdf_text(paper_dir=paper_dir, manifest=manifest)
    source_latex = _source_latex_text(document)

    for surface in _reader_text_surfaces(document=document, manifest=manifest):
        text = surface["text"]
        if not text:
            continue
        findings = _symbol_findings(text, skip_latex_commands=bool(surface.get("skipLatexCommands")))
        for finding in findings:
            origin = _symbol_origin(finding["sample"], native_text=native_text, source_latex=source_latex)
            issue = _issue(
                finding["code"],
                finding["message"],
                gate="symbol",
                paper_id=paper_id,
                origin=origin,
                surface=surface["surface"],
                blockId=surface.get("blockId"),
                assetId=surface.get("assetId"),
                sample=finding["sample"],
            )
            if origin == "native_pdf":
                warnings.append(issue)
            else:
                errors.append(issue)
    return errors, warnings


def _symbol_findings(text: str, *, skip_latex_commands: bool) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    if _CONTROL_CHARACTER_PATTERN.search(text):
        findings.append({"code": "control_character_visible", "message": "reader-facing text contains non-printing control characters", "sample": _sample(text)})
    mojibake = _MOJIBAKE_PATTERN.search(text)
    if mojibake:
        findings.append({"code": "mojibake_sequence_visible", "message": "reader-facing text contains likely mojibake or replacement characters", "sample": _sample(_context(text, mojibake.start(), mojibake.end()))})
    entity = _HTML_ENTITY_LEAK_PATTERN.search(text)
    if entity:
        findings.append({"code": "html_entity_visible", "message": "escaped HTML entity is visible in reader-facing text", "sample": _sample(_context(text, entity.start(), entity.end()))})
    if _looks_like_unparsed_table_alignment(text):
        findings.append({"code": "table_alignment_symbols_visible", "message": "TeX table alignment symbols are visible in reader-facing text", "sample": _sample(text)})
    env = None if skip_latex_commands else _LATEX_ENV_LEAK_PATTERN.search(text)
    if env:
        findings.append({"code": "latex_environment_visible", "message": "raw LaTeX environment syntax is visible in reader-facing text", "sample": _sample(_context(text, env.start(), env.end()))})
    command = None if skip_latex_commands else _LATEX_TEXT_COMMAND_LEAK_PATTERN.search(text)
    if command:
        findings.append({"code": "latex_text_command_visible", "message": "raw LaTeX text command is visible in reader-facing text", "sample": _sample(_context(text, command.start(), command.end()))})
    generic_command = None if skip_latex_commands or env or command else _LATEX_READER_COMMAND_LEAK_PATTERN.search(text)
    if generic_command:
        findings.append({"code": "latex_command_visible", "message": "raw LaTeX command is visible in reader-facing text", "sample": _sample(_context(text, generic_command.start(), generic_command.end()))})
    return findings


def _reader_text_surfaces(*, document: Mapping[str, Any], manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    surfaces: list[dict[str, Any]] = []
    for block in _blocks(document):
        block_id = _text(block.get("id"))
        block_type = _text(block.get("type"))
        metadata = _mapping(block.get("metadata")) or {}
        skip_latex = block_type == "equation"
        for surface_name, value in (
            ("block.text", block.get("text")),
            ("block.caption", block.get("caption")),
            ("metadata.inlineText", metadata.get("inlineText")),
            ("metadata.tableText", metadata.get("tableText")),
        ):
            text = _text(value)
            if text:
                surfaces.append({"surface": surface_name, "blockId": block_id, "text": text, "skipLatexCommands": skip_latex})
        table_model = _mapping(metadata.get("tableModel"))
        if table_model is not None:
            table_text = _table_model_text(table_model)
            if table_text:
                surfaces.append({"surface": "metadata.tableModel", "blockId": block_id, "assetId": _text(block.get("assetId")), "text": table_text})
    for asset in _assets(manifest):
        if _text(asset.get("kind")) != "table":
            continue
        metadata = _mapping(asset.get("metadata")) or {}
        asset_id = _text(asset.get("assetId"))
        for surface_name, value in (
            ("asset.caption", asset.get("caption")),
            ("asset.metadata.tableText", metadata.get("tableText")),
        ):
            text = _text(value)
            if text:
                surfaces.append({"surface": surface_name, "assetId": asset_id, "text": text})
        table_model = _mapping(metadata.get("tableModel"))
        if table_model is not None:
            table_text = _table_model_text(table_model)
            if table_text:
                surfaces.append({"surface": "asset.metadata.tableModel", "assetId": asset_id, "text": table_text})
    return surfaces


def _review_memory_result(
    *,
    issues: Sequence[Mapping[str, Any]],
    paper_id: str,
    memory_path: Path | None,
    now: str,
) -> dict[str, Any]:
    if memory_path is None:
        return {"attempted": False, "saved": False, "matches": {}}
    try:
        memory = _read_memory(memory_path)
        matches = _memory_matches(memory, issues)
        _write_memory(memory_path, memory, issues=issues, paper_id=paper_id, now=now)
        return {"attempted": True, "saved": True, "journalRef": str(memory_path.resolve()), "matches": matches}
    except Exception as exc:
        warning = _issue("artifact_review_memory_failed", "artifact review issue memory could not be persisted", gate="symbol", paper_id=paper_id, error=str(exc))
        return {"attempted": True, "saved": False, "journalRef": str(memory_path.resolve()), "matches": {}, "error": str(exc), "warning": warning}


def _read_memory(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schemaVersion": MEMORY_SCHEMA_VERSION, "issues": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schemaVersion": MEMORY_SCHEMA_VERSION, "issues": {}}
    if not isinstance(payload, dict):
        return {"schemaVersion": MEMORY_SCHEMA_VERSION, "issues": {}}
    issues = payload.get("issues")
    if not isinstance(issues, dict):
        payload["issues"] = {}
    payload["schemaVersion"] = MEMORY_SCHEMA_VERSION
    return payload


def _write_memory(path: Path, memory: dict[str, Any], *, issues: Sequence[Mapping[str, Any]], paper_id: str, now: str) -> None:
    stored = memory.setdefault("issues", {})
    if not isinstance(stored, dict):
        stored = {}
        memory["issues"] = stored
    for issue in issues:
        fingerprint = _text(issue.get("fingerprint"))
        if not fingerprint:
            continue
        current = stored.get(fingerprint)
        if not isinstance(current, dict):
            current = {
                "fingerprint": fingerprint,
                "firstSeenAt": now,
                "seenCount": 0,
                "paperIds": [],
                "samples": [],
                "occurrences": [],
            }
        current["lastSeenAt"] = now
        current["seenCount"] = int(current.get("seenCount") or 0) + 1
        current["gate"] = _text(issue.get("gate"))
        current["code"] = _text(issue.get("code"))
        current["message"] = _text(issue.get("message"))
        locator = dict(issue.get("locator")) if isinstance(issue.get("locator"), Mapping) else _locator_for_issue(issue, paper_id)
        current["lastLocator"] = locator
        current["lastIssue"] = _memory_issue_summary(issue)
        paper_ids = [str(item) for item in current.get("paperIds", []) if str(item)]
        if paper_id and paper_id not in paper_ids:
            paper_ids.append(paper_id)
        current["paperIds"] = paper_ids[-12:]
        sample = _text(issue.get("sample"))
        samples = [str(item) for item in current.get("samples", []) if str(item)]
        if sample and sample not in samples:
            samples.append(sample)
        current["samples"] = samples[-8:]
        occurrence = {
            "seenAt": now,
            "paperId": paper_id,
            "locator": locator,
        }
        if sample:
            occurrence["sample"] = sample
        occurrences = [item for item in current.get("occurrences", []) if isinstance(item, Mapping)]
        occurrences.append(occurrence)
        current["occurrences"] = occurrences[-24:]
        stored[fingerprint] = current
    memory["updatedAt"] = now
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_text(json.dumps(memory, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(path)


def _memory_matches(memory: Mapping[str, Any], issues: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    stored = memory.get("issues")
    if not isinstance(stored, Mapping):
        return {}
    matches: dict[str, dict[str, Any]] = {}
    for issue in issues:
        fingerprint = _text(issue.get("fingerprint"))
        existing = stored.get(fingerprint) if fingerprint else None
        if not isinstance(existing, Mapping):
            continue
        matches[fingerprint] = {
            "fingerprint": fingerprint,
            "gate": _text(existing.get("gate")),
            "code": _text(existing.get("code")),
            "seenCount": int(existing.get("seenCount") or 0),
            "firstSeenAt": _text(existing.get("firstSeenAt")),
            "lastSeenAt": _text(existing.get("lastSeenAt")),
            "lastLocator": dict(existing.get("lastLocator")) if isinstance(existing.get("lastLocator"), Mapping) else {},
            "recentLocators": _recent_memory_locators(existing),
            "samples": list(existing.get("samples")) if isinstance(existing.get("samples"), list) else [],
        }
    return matches


def _recent_memory_locators(entry: Mapping[str, Any]) -> list[dict[str, Any]]:
    occurrences = entry.get("occurrences")
    if not isinstance(occurrences, Sequence) or isinstance(occurrences, (str, bytes)):
        return []
    locators: list[dict[str, Any]] = []
    seen: set[str] = set()
    for occurrence in reversed(occurrences):
        if not isinstance(occurrence, Mapping) or not isinstance(occurrence.get("locator"), Mapping):
            continue
        locator = dict(occurrence["locator"])
        key = json.dumps(locator, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        locators.append(locator)
        if len(locators) >= 6:
            break
    return locators


def _attach_memory_match(issue: dict[str, Any], memory_result: Mapping[str, Any]) -> dict[str, Any]:
    matches = memory_result.get("matches")
    if not isinstance(matches, Mapping):
        return issue
    match = matches.get(_text(issue.get("fingerprint")))
    if not isinstance(match, Mapping):
        return issue
    return {**issue, "memoryMatch": dict(match)}


def _dedupe_issues(issues: Sequence[dict[str, Any]], *, seen: set[str] | None = None) -> list[dict[str, Any]]:
    fingerprints = set(seen or set())
    deduped: list[dict[str, Any]] = []
    for issue in issues:
        fingerprint = _text(issue.get("fingerprint"))
        if fingerprint and fingerprint in fingerprints:
            continue
        if fingerprint:
            fingerprints.add(fingerprint)
        deduped.append(issue)
    return deduped


def _issue(code: str, message: str, *, gate: str, paper_id: str, **details: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message, "gate": gate}
    payload.update({key: value for key, value in details.items() if value not in (None, "", [], {})})
    payload["locator"] = _locator_for_issue(payload, paper_id)
    payload["fingerprint"] = _fingerprint(payload)
    return payload


def _fingerprint(issue: Mapping[str, Any]) -> str:
    sample = _normalize_for_origin(_text(issue.get("sample")))
    basis = {
        "gate": _text(issue.get("gate")),
        "code": _text(issue.get("code")),
        "origin": _text(issue.get("origin")),
        "sample": sample[:120],
    }
    return hashlib.sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def _locator_for_issue(issue: Mapping[str, Any], paper_id: str) -> dict[str, Any]:
    locator = {"paperId": paper_id}
    for key in ("blockId", "assetId", "surface", "origin", "spanIndex"):
        value = issue.get(key)
        if value not in (None, "", [], {}):
            locator[key] = value
    return locator


def _memory_issue_summary(issue: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: issue[key]
        for key in ("code", "message", "gate", "surface", "origin", "sample", "locator")
        if key in issue and issue[key] not in (None, "", [], {})
    }


def _gate_summaries(*, errors: Sequence[Mapping[str, Any]], warnings: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        {
            "name": gate,
            "passed": not any(_issue_gate(issue) == gate for issue in errors),
            "errorCount": sum(1 for issue in errors if _issue_gate(issue) == gate),
            "warningCount": sum(1 for issue in warnings if _issue_gate(issue) == gate),
        }
        for gate in ("image", "table", "equation", "symbol")
    ]


def _issue_gate(issue: Mapping[str, Any]) -> str:
    gate = _text(issue.get("gate"))
    if gate:
        return gate
    code = _text(issue.get("code"))
    if code.startswith("table_"):
        return "table"
    if code.startswith("equation_") or code.startswith("inline_equation_"):
        return "equation"
    if "mojibake" in code or "html_entity" in code or "latex_" in code or "alignment_symbols" in code or "control_character" in code:
        return "symbol"
    return "image"


def _summary(errors: Sequence[Mapping[str, Any]], warnings: Sequence[Mapping[str, Any]]) -> str:
    if errors:
        return f"artifact review blocked publication with {len(errors)} error(s) and {len(warnings)} warning(s)"
    if warnings:
        return f"artifact review passed with {len(warnings)} warning(s)"
    return "artifact review passed"


def _table_model_has_readable_cells(model: Mapping[str, Any]) -> bool:
    if _text(model.get("sourceKind")) == "pdf-raster-table-model" and _text(model.get("textExtraction")) == "unavailable":
        return bool(_table_model_cells(model))
    return any(_text(cell.get("text")) or _text(cell.get("html")) for cell in _table_model_cells(model))


def _table_model_text(model: Mapping[str, Any] | None) -> str:
    if model is None:
        return ""
    return "\n".join(
        _visible_html_text(_text(cell.get("html"))) or _text(cell.get("text"))
        for cell in _table_model_cells(model)
        if _visible_html_text(_text(cell.get("html"))) or _text(cell.get("text"))
    )


def _table_model_cells(model: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    cells: list[Mapping[str, Any]] = []
    rows = model.get("rows")
    if not isinstance(rows, list | tuple):
        return cells
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        row_cells = row.get("cells")
        if not isinstance(row_cells, list | tuple):
            continue
        cells.extend(cell for cell in row_cells if isinstance(cell, Mapping))
    return cells


def _looks_like_unparsed_table_alignment(value: str) -> bool:
    text = " ".join(value.split())
    return bool(text and _TABLE_ALIGNMENT_LEAK_PATTERN.search(text) and ("&" in text or "&amp;" in text))


def _symbol_origin(sample: str, *, native_text: str, source_latex: str) -> str:
    normalized_sample = _normalize_for_origin(sample)
    if not normalized_sample:
        return "reader_parse"
    if native_text and normalized_sample in _normalize_for_origin(native_text):
        return "native_pdf"
    if source_latex and normalized_sample in _normalize_for_origin(source_latex):
        return "source_latex"
    return "reader_parse"


def _source_latex_text(document: Mapping[str, Any]) -> str:
    chunks: list[str] = []
    for block in _blocks(document):
        metadata = _mapping(block.get("metadata")) or {}
        latex = metadata.get("latex")
        if isinstance(latex, str):
            chunks.append(latex)
    return "\n".join(chunks)


def _native_pdf_text(*, paper_dir: Path | None, manifest: Mapping[str, Any]) -> str:
    if paper_dir is None:
        return ""
    file_name = _text(manifest.get("sourcePdfFileName"))
    if not file_name:
        return ""
    path = (paper_dir / file_name).resolve()
    root = paper_dir.resolve()
    if root not in path.parents and path != root:
        return ""
    if not path.exists() or not path.is_file():
        return ""
    try:
        import fitz  # type: ignore[import-not-found]

        pdf = fitz.open(path)
    except Exception:
        return ""
    try:
        return "\n".join(page.get_text("text") for page in pdf)
    finally:
        pdf.close()


def _blank_ratio_for_asset(*, asset: Mapping[str, Any], paper_dir: Path | None) -> float | None:
    path = _asset_file_path(asset=asset, paper_dir=paper_dir)
    if path is None:
        return None
    return _blank_ratio(path)


def _asset_file_path(*, asset: Mapping[str, Any], paper_dir: Path | None) -> Path | None:
    if paper_dir is None:
        return None
    file_name = _text(asset.get("fileName"))
    if not file_name:
        return None
    path = (paper_dir / file_name).resolve()
    root = paper_dir.resolve()
    if root not in path.parents and path != root:
        return None
    if not path.exists() or not path.is_file():
        return None
    return path


def _blank_ratio(path: Path) -> float:
    try:
        import fitz  # type: ignore[import-not-found]

        pixmap = fitz.Pixmap(str(path))
    except Exception:
        return 1.0
    samples = bytes(pixmap.samples)
    channels = max(1, int(getattr(pixmap, "n", 3) or 3))
    if not samples or channels < 3:
        return 1.0
    pixel_count = len(samples) // channels
    if pixel_count <= 0:
        return 1.0
    step = max(1, pixel_count // 30_000)
    blank = 0
    sampled = 0
    for pixel_index in range(0, pixel_count, step):
        offset = pixel_index * channels
        r, g, b = samples[offset], samples[offset + 1], samples[offset + 2]
        if r >= 248 and g >= 248 and b >= 248:
            blank += 1
        sampled += 1
    return blank / sampled if sampled else 1.0


def png_size(path: Path) -> tuple[int, int] | None:
    try:
        with path.open("rb") as handle:
            header = handle.read(24)
    except OSError:
        return None
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", header[16:24])


def _visible_html_text(value: str) -> str:
    if not value:
        return ""
    stripped = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(stripped).split())


def _normalize_for_origin(value: str) -> str:
    return " ".join(html.unescape(value).casefold().split())


def _context(text: str, start: int, end: int, radius: int = 36) -> str:
    return text[max(0, start - radius): min(len(text), end + radius)]


def _sample(value: str, limit: int = 160) -> str:
    text = " ".join(value.split())
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def _paper_id(document: Mapping[str, Any], manifest: Mapping[str, Any]) -> str:
    return _text(document.get("paperId")) or _text(manifest.get("paperId")) or "unknown-paper"


def _assets(manifest: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [item for item in _sequence(manifest.get("assets")) if isinstance(item, Mapping)]


def _blocks(document: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    return [item for item in _sequence(document.get("blocks")) if isinstance(item, Mapping)]


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes)) else []


def _mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, float) and value.is_integer() and value > 0:
        return int(value)
    if isinstance(value, str):
        try:
            parsed = int(value.strip())
        except ValueError:
            return None
        return parsed if parsed > 0 else None
    return None


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _optional_path(value: Any) -> Path | None:
    if value is None:
        return None
    text = str(value).strip()
    return Path(text).expanduser().resolve() if text else None


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
