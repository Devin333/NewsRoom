from __future__ import annotations

import json
import os
import shutil
import time
from hashlib import sha256
from pathlib import Path
from typing import Any

from business.foundation import build_stable_id
from business.research.document.docker_pdf_parser import (
    first_existing_file,
    metadata_text,
    page_rects,
    rect_to_pdf_points,
    run_docker_command,
    source_locator,
    stage_pdf_for_docker,
)
from business.research.domain.common import SourceLineage
from business.research.domain.document import (
    ResearchDocument,
    ResearchEquation,
    ResearchFigure,
    ResearchSection,
    ResearchTable,
)


class MarkerPdfDocumentParser:
    """Docker-backed Marker parser for PDF parser bake-off experiments."""

    def parse(self, paper_id: str, source_bytes: bytes) -> ResearchDocument:
        source_hash = sha256(source_bytes).hexdigest()
        source_ref = f"arxiv://{paper_id}/pdf"
        started_at = time.perf_counter()
        input_dir, output_dir, _pdf_path = stage_pdf_for_docker(
            backend="marker",
            paper_id=paper_id,
            pdf_bytes=source_bytes,
        )
        command = _marker_command(input_dir=input_dir, output_dir=output_dir)
        run_docker_command(command, timeout_seconds=_marker_timeout_seconds())
        return _document_from_marker_output(
            paper_id=paper_id,
            source_ref=source_ref,
            source_hash=source_hash,
            pdf_bytes=source_bytes,
            output_dir=output_dir,
            duration_seconds=time.perf_counter() - started_at,
            command=command,
        )


def _marker_command(*, input_dir: Path, output_dir: Path) -> list[str]:
    image = os.environ.get("NEWSROOM_MARKER_DOCKER_IMAGE", "newsroom-marker:latest").strip()
    extra_args = _split_env_args(os.environ.get("NEWSROOM_MARKER_DOCKER_ARGS", ""))
    return [
        "docker",
        "run",
        "--rm",
        "--gpus",
        "all",
        "-e",
        "TORCH_DEVICE=cuda",
        *extra_args,
        "-v",
        f"{input_dir.resolve()}:/input",
        "-v",
        f"{output_dir.resolve()}:/output",
        image,
        "marker_single",
        "/input/input.pdf",
        "--output_format",
        "json",
        "--output_dir",
        "/output",
        "--paginate_output",
        "--debug",
    ]


def _split_env_args(raw: str) -> list[str]:
    return [part for part in raw.split() if part.strip()]


def _marker_timeout_seconds() -> int:
    raw = os.environ.get("NEWSROOM_MARKER_TIMEOUT_SECONDS", "1800")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("NEWSROOM_MARKER_TIMEOUT_SECONDS must be an integer") from exc
    if value <= 0:
        raise ValueError("NEWSROOM_MARKER_TIMEOUT_SECONDS must be positive")
    return value


def _document_from_marker_output(
    *,
    paper_id: str,
    source_ref: str,
    source_hash: str,
    pdf_bytes: bytes,
    output_dir: Path,
    duration_seconds: float,
    command: list[str],
) -> ResearchDocument:
    json_path = _marker_json_path(output_dir)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    blocks = _extract_blocks(payload)
    rects = page_rects(pdf_bytes)
    artifact_root = _paper_artifact_dir(paper_id)
    figures_dir = artifact_root / "figures"
    tables_dir = artifact_root / "tables"
    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    sections: list[ResearchSection] = []
    equations: list[ResearchEquation] = []
    figures: list[ResearchFigure] = []
    tables: list[ResearchTable] = []
    warnings: list[str] = []

    current_title = "Document"
    current_level = 1
    current_parts: list[str] = []
    current_page: int | None = None
    section_index = 0

    def flush_section() -> None:
        nonlocal current_parts, current_title, current_level, current_page, section_index
        text = "\n\n".join(part for part in current_parts if part.strip()).strip()
        if not text:
            current_parts = []
            return
        locator = source_locator(source_ref, page=current_page)
        sections.append(ResearchSection(
            section_id=build_stable_id("sec", paper_id, current_title, str(section_index)),
            title=current_title,
            level=max(1, current_level),
            text=text,
            page_start=current_page,
            page_end=current_page,
            source_ref=locator,
            metadata={
                "parse_source": "marker",
                "source_locator": locator,
            },
        ))
        section_index += 1
        current_parts = []

    for index, block in enumerate(blocks):
        kind = _block_kind(block)
        page = _block_page(block)
        pdf_rect = _block_pdf_rect(block, rects)
        locator = source_locator(source_ref, page=page, pdf_rect=pdf_rect)
        if kind == "sectionheader":
            flush_section()
            current_title = _block_text(block) or f"Section {section_index + 1}"
            current_level = _heading_level(block)
            current_page = page
            continue
        if kind in {"text", "textinlinemath", "listitem"}:
            text = _block_text(block)
            if text:
                if current_page is None:
                    current_page = page
                current_parts.append(text)
            continue
        if kind == "equation":
            latex = _block_text(block)
            if latex:
                equations.append(ResearchEquation(
                    equation_id=build_stable_id("eq", paper_id, "marker", str(index), latex[:80]),
                    latex=latex,
                    source_ref=locator,
                    page=page,
                    metadata={
                        "parse_source": "marker",
                        "source_locator": locator,
                        "pdf_rect": list(pdf_rect) if pdf_rect else None,
                        "marker_block": _compact_block_metadata(block),
                    },
                ))
            continue
        if kind in {"figure", "figuregroup", "picture", "picturegroup"}:
            caption = _block_caption(block) or _block_text(block) or f"Figure from page {page or '?'}"
            image_ref = _copy_marker_asset(block, json_path.parent, figures_dir)
            figures.append(ResearchFigure(
                figure_id=build_stable_id("fig", paper_id, "marker", str(index), caption),
                caption=caption[:500],
                source_ref=locator,
                image_ref=image_ref,
                page=page,
                metadata={
                    "parse_source": "marker",
                    "source_locator": locator,
                    "pdf_rect": list(pdf_rect) if pdf_rect else None,
                    "marker_block": _compact_block_metadata(block),
                    **({"image_ref": image_ref} if image_ref else {}),
                },
            ))
            continue
        if kind in {"table", "tablegroup"}:
            caption = _block_caption(block) or f"Table from page {page or '?'}"
            columns, rows = _table_rows(block)
            image_ref = _copy_marker_asset(block, json_path.parent, tables_dir)
            tables.append(ResearchTable(
                table_id=build_stable_id("tbl", paper_id, "marker", str(index), caption),
                caption=caption[:500],
                source_ref=locator,
                columns=columns,
                rows=rows,
                page=page,
                metadata={
                    "parse_source": "marker",
                    "source_locator": locator,
                    "pdf_rect": list(pdf_rect) if pdf_rect else None,
                    "table_structure_source": "marker_json",
                    "marker_block": _compact_block_metadata(block),
                    **({"image_ref": image_ref} if image_ref else {}),
                },
            ))
            continue
        warnings.append(f"block_{index}: unsupported Marker block_type {kind!r}")

    flush_section()
    return ResearchDocument(
        paper_id=paper_id,
        source_hash=source_hash,
        sections=sections,
        figures=figures,
        tables=tables,
        equations=equations,
        lineage=SourceLineage(source_refs=[source_ref], source_hash=source_hash),
        metadata={
            "parse_source": "marker",
            "parser_backend": "marker",
            "parser_output_ref": str(output_dir),
            "parser_duration_seconds": round(duration_seconds, 3),
            "parser_command": _redacted_command(command),
            "parser_warnings": warnings,
            "parse_quality": _parse_quality(sections, figures, tables, equations),
        },
    )


def _marker_json_path(output_dir: Path) -> Path:
    path = first_existing_file(output_dir, ("input.json", "input_meta.json", "output.json"))
    if path is not None:
        return path
    matches = [path for path in output_dir.rglob("*.json") if path.is_file()]
    if not matches:
        raise FileNotFoundError(f"Marker did not produce a JSON file under {output_dir}")
    return matches[0]


def _extract_blocks(payload: Any) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []

    def visit(node: Any, inherited_page: int | None = None) -> None:
        if isinstance(node, list):
            for item in node:
                visit(item, inherited_page)
            return
        if not isinstance(node, dict):
            return
        page = _block_page(node) or inherited_page
        children = node.get("children") or node.get("blocks")
        if _block_kind(node) not in {"document", "page", "unknown"}:
            block = dict(node)
            if page is not None and "page" not in block and "page_id" not in block:
                block["page"] = page
            blocks.append(block)
        if children is not None:
            visit(children, page)
        for key in ("pages",):
            if key in node:
                visit(node[key], page)

    visit(payload)
    return blocks


def _block_kind(block: dict[str, Any]) -> str:
    raw = block.get("block_type") or block.get("type") or block.get("kind") or ""
    return str(raw).strip().lower().replace("_", "")


def _block_page(block: dict[str, Any]) -> int | None:
    for key in ("page", "page_id", "page_number"):
        if key not in block:
            continue
        try:
            value = int(block[key])
        except (TypeError, ValueError):
            continue
        return value + 1 if value == 0 else value
    return None


def _block_pdf_rect(
    block: dict[str, Any],
    rects: dict[int, Any],
) -> tuple[float, float, float, float] | None:
    page = _block_page(block)
    page_rect = rects.get(page or -1)
    if page_rect is None:
        return None
    return rect_to_pdf_points(
        block.get("polygon") or block.get("bbox") or block.get("poly"),
        page_rect=page_rect,
    )


def _heading_level(block: dict[str, Any]) -> int:
    for key in ("heading_level", "level"):
        try:
            return max(1, int(block[key]))
        except (KeyError, TypeError, ValueError):
            continue
    return 1


def _block_text(block: dict[str, Any]) -> str:
    return metadata_text(
        block.get("html")
        or block.get("text")
        or block.get("content")
        or block.get("markdown")
        or block.get("latex")
    )


def _block_caption(block: dict[str, Any]) -> str:
    return metadata_text(
        block.get("caption")
        or block.get("caption_text")
        or block.get("description")
    )


def _table_rows(block: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    rows_value = block.get("rows") or block.get("table_rows")
    if isinstance(rows_value, list) and rows_value:
        if all(isinstance(row, dict) for row in rows_value):
            columns: list[str] = []
            for row in rows_value:
                for key in row:
                    if str(key) not in columns:
                        columns.append(str(key))
            return columns, [dict(row) for row in rows_value if isinstance(row, dict)]
        if all(isinstance(row, list) for row in rows_value):
            matrix = [[metadata_text(cell) for cell in row] for row in rows_value]
            return _matrix_to_rows(matrix)
    html = _block_text(block)
    if "|" in html:
        matrix = [
            [cell.strip() for cell in line.strip("|").split("|")]
            for line in html.splitlines()
            if "|" in line
        ]
        return _matrix_to_rows(matrix)
    return [], []


def _matrix_to_rows(matrix: list[list[str]]) -> tuple[list[str], list[dict[str, Any]]]:
    matrix = [[cell for cell in row if cell] for row in matrix if any(cell for cell in row)]
    if len(matrix) < 2:
        return [], []
    width = max(len(row) for row in matrix)
    columns = _unique_columns(matrix[0] + [f"column_{i + 1}" for i in range(len(matrix[0]), width)])
    rows: list[dict[str, Any]] = []
    for row in matrix[1:]:
        padded = row + [""] * max(0, width - len(row))
        rows.append(dict(zip(columns, padded[: len(columns)])))
    return columns, rows


def _unique_columns(values: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    out: list[str] = []
    for index, value in enumerate(values):
        name = value.strip() or f"column_{index + 1}"
        counts[name] = counts.get(name, 0) + 1
        if counts[name] > 1:
            name = f"{name}_{counts[name]}"
        out.append(name)
    return out


def _copy_marker_asset(block: dict[str, Any], output_root: Path, target_dir: Path) -> str | None:
    raw = metadata_text(
        block.get("image_path")
        or block.get("img_path")
        or block.get("file_path")
    )
    if not raw:
        images = block.get("images")
        if isinstance(images, dict) and images:
            raw = metadata_text(next(iter(images.values())))
        elif isinstance(images, list) and images:
            raw = metadata_text(images[0])
    if not raw:
        return None
    source = Path(raw)
    if not source.is_absolute():
        source = output_root / source
    if not source.exists():
        return raw
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / source.name
    if source.resolve() != target.resolve():
        shutil.copyfile(source, target)
    return str(target)


def _paper_artifact_dir(paper_id: str) -> Path:
    root = Path(os.environ.get("NEWS_ARTIFACT_ROOT", ".newsroom/runs"))
    return root.parent / "papers" / paper_id


def _compact_block_metadata(block: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "block_type",
        "type",
        "page",
        "page_id",
        "polygon",
        "bbox",
        "image_path",
        "img_path",
    )
    return {key: block[key] for key in keys if key in block}


def _parse_quality(
    sections: list[ResearchSection],
    figures: list[ResearchFigure],
    tables: list[ResearchTable],
    equations: list[ResearchEquation],
) -> dict[str, Any]:
    return {
        "sections": {
            "total": len(sections),
            "with_page_bounds": sum(1 for item in sections if item.page_start is not None),
            "with_source_locator": sum(1 for item in sections if item.metadata.get("source_locator")),
        },
        "figures": {
            "total": len(figures),
            "with_image": sum(1 for item in figures if item.image_ref),
            "with_bbox": sum(1 for item in figures if item.metadata.get("pdf_rect")),
            "with_source_locator": sum(1 for item in figures if item.metadata.get("source_locator")),
        },
        "tables": {
            "total": len(tables),
            "with_rows": sum(1 for item in tables if item.rows),
            "with_image": sum(1 for item in tables if item.metadata.get("image_ref")),
            "with_bbox": sum(1 for item in tables if item.metadata.get("pdf_rect")),
            "with_source_locator": sum(1 for item in tables if item.metadata.get("source_locator")),
        },
        "equations": {
            "total": len(equations),
            "with_bbox": sum(1 for item in equations if item.metadata.get("pdf_rect")),
            "with_source_locator": sum(1 for item in equations if item.metadata.get("source_locator")),
        },
    }


def _redacted_command(command: list[str]) -> list[str]:
    return ["<repo-path>" if "NewsRoom" in part else part for part in command]


__all__ = ["MarkerPdfDocumentParser"]
