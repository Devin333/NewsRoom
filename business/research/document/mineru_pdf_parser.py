from __future__ import annotations

import json
import os
import re
import shutil
import time
from hashlib import sha256
from html.parser import HTMLParser
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


class MinerUPdfDocumentParser:
    """Docker-backed MinerU parser for PDF parser bake-off experiments."""

    def parse(self, paper_id: str, source_bytes: bytes) -> ResearchDocument:
        source_hash = sha256(source_bytes).hexdigest()
        source_ref = f"arxiv://{paper_id}/pdf"
        started_at = time.perf_counter()
        input_dir, output_dir, _pdf_path = stage_pdf_for_docker(
            backend="mineru",
            paper_id=paper_id,
            pdf_bytes=source_bytes,
        )
        command = _mineru_command(input_dir=input_dir, output_dir=output_dir)
        run_docker_command(command, timeout_seconds=_mineru_timeout_seconds())
        document = _document_from_mineru_output(
            paper_id=paper_id,
            source_ref=source_ref,
            source_hash=source_hash,
            pdf_bytes=source_bytes,
            output_dir=output_dir,
            duration_seconds=time.perf_counter() - started_at,
            command=command,
        )
        return document


def _mineru_command(*, input_dir: Path, output_dir: Path) -> list[str]:
    image = os.environ.get("NEWSROOM_MINERU_DOCKER_IMAGE", "mineru:latest").strip()
    extra_args = _split_env_args(os.environ.get("NEWSROOM_MINERU_DOCKER_ARGS", ""))
    model_source = os.environ.get("NEWSROOM_MINERU_MODEL_SOURCE", "modelscope").strip() or "modelscope"
    cache_dir = os.environ.get("NEWSROOM_MINERU_CACHE_DIR", "").strip()
    config_dir = os.environ.get("NEWSROOM_MINERU_CONFIG_DIR", "").strip()
    return [
        "docker",
        "run",
        "--rm",
        "--gpus",
        "all",
        "-e",
        f"MINERU_MODEL_SOURCE={model_source}",
        *extra_args,
        *(
            [
                "-v",
                f"{Path(cache_dir).resolve()}:/root/.cache",
            ]
            if cache_dir
            else []
        ),
        *(
            [
                "-v",
                f"{Path(config_dir).resolve()}:/root",
            ]
            if config_dir
            else []
        ),
        "-v",
        f"{input_dir.resolve()}:/input",
        "-v",
        f"{output_dir.resolve()}:/output",
        image,
        "mineru",
        "-p",
        "/input/input.pdf",
        "-o",
        "/output",
        "-b",
        "pipeline",
    ]


def _split_env_args(raw: str) -> list[str]:
    return [part for part in raw.split() if part.strip()]


def _mineru_timeout_seconds() -> int:
    raw = os.environ.get("NEWSROOM_MINERU_TIMEOUT_SECONDS", "1800")
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError("NEWSROOM_MINERU_TIMEOUT_SECONDS must be an integer") from exc
    if value <= 0:
        raise ValueError("NEWSROOM_MINERU_TIMEOUT_SECONDS must be positive")
    return value


def _document_from_mineru_output(
    *,
    paper_id: str,
    source_ref: str,
    source_hash: str,
    pdf_bytes: bytes,
    output_dir: Path,
    duration_seconds: float,
    command: list[str],
) -> ResearchDocument:
    content_path = _mineru_content_list_path(output_dir)
    if content_path is None:
        raise FileNotFoundError(f"MinerU did not produce content_list.json under {output_dir}")
    blocks = _load_json_list(content_path)
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
        page = current_page
        locator = source_locator(source_ref, page=page)
        sections.append(ResearchSection(
            section_id=build_stable_id("sec", paper_id, current_title, str(section_index)),
            title=current_title,
            level=max(1, current_level),
            text=text,
            page_start=page,
            page_end=page,
            source_ref=locator,
            metadata={
                "parse_source": "mineru",
                "source_locator": locator,
            },
        ))
        section_index += 1
        current_parts = []

    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            warnings.append(f"block_{index}: non-object block skipped")
            continue
        kind = _block_kind(block)
        page = _block_page(block)
        pdf_rect = _block_pdf_rect(block, rects)
        locator = source_locator(source_ref, page=page, pdf_rect=pdf_rect)
        if kind == "text":
            text = _block_text(block)
            if not text:
                continue
            level = _block_text_level(block)
            if level is not None:
                flush_section()
                current_title = text[:160]
                current_level = level
                current_page = page
                continue
            if current_page is None:
                current_page = page
            current_parts.append(text)
            continue
        if kind == "equation":
            latex = _block_equation_text(block)
            if latex:
                equations.append(ResearchEquation(
                    equation_id=build_stable_id("eq", paper_id, "mineru", str(index), latex[:80]),
                    latex=latex,
                    source_ref=locator,
                    page=page,
                    metadata={
                        "parse_source": "mineru",
                        "source_locator": locator,
                        "pdf_rect": list(pdf_rect) if pdf_rect else None,
                        "mineru_block": _compact_block_metadata(block),
                    },
                ))
            continue
        if kind in {"image", "chart", "figure"}:
            caption = _block_caption(block) or f"Figure from page {page or '?'}"
            image_ref = _copy_block_asset(block, content_path.parent, figures_dir)
            figures.append(ResearchFigure(
                figure_id=build_stable_id("fig", paper_id, "mineru", str(index), caption),
                caption=caption[:500],
                source_ref=locator,
                image_ref=image_ref,
                page=page,
                metadata={
                    "parse_source": "mineru",
                    "source_locator": locator,
                    "pdf_rect": list(pdf_rect) if pdf_rect else None,
                    "mineru_block": _compact_block_metadata(block),
                    **({"image_ref": image_ref} if image_ref else {}),
                },
            ))
            continue
        if kind == "table":
            caption = _block_caption(block) or f"Table from page {page or '?'}"
            columns, rows = _table_rows(block)
            image_ref = _copy_block_asset(block, content_path.parent, tables_dir)
            tables.append(ResearchTable(
                table_id=build_stable_id("tbl", paper_id, "mineru", str(index), caption),
                caption=caption[:500],
                source_ref=locator,
                columns=columns,
                rows=rows,
                page=page,
                metadata={
                    "parse_source": "mineru",
                    "source_locator": locator,
                    "pdf_rect": list(pdf_rect) if pdf_rect else None,
                    "table_structure_source": "mineru_content_list",
                    "mineru_block": _compact_block_metadata(block),
                    **({"image_ref": image_ref} if image_ref else {}),
                },
            ))
            continue
        if kind in _IGNORED_BLOCK_KINDS:
            continue
        warnings.append(f"block_{index}: unsupported MinerU type {kind!r}")

    flush_section()
    metadata = {
        "parse_source": "mineru",
        "parser_backend": "mineru",
        "parser_output_ref": str(output_dir),
        "parser_duration_seconds": round(duration_seconds, 3),
        "parser_command": _redacted_command(command),
        "parser_warnings": warnings,
        "parse_quality": _parse_quality(sections, figures, tables, equations),
    }
    return ResearchDocument(
        paper_id=paper_id,
        source_hash=source_hash,
        sections=sections,
        figures=figures,
        tables=tables,
        equations=equations,
        lineage=SourceLineage(source_refs=[source_ref], source_hash=source_hash),
        metadata=metadata,
    )


def _load_json_list(path: Path) -> list[Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("content", "blocks", "items", "pages"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    raise ValueError(f"MinerU content file must contain a list: {path}")


def _mineru_content_list_path(output_dir: Path) -> Path | None:
    path = first_existing_file(output_dir, ("content_list.json", "input_content_list.json"))
    if path is not None:
        return path
    matches = sorted(path for path in output_dir.rglob("*_content_list.json") if path.is_file())
    return matches[0] if matches else None


def _block_kind(block: dict[str, Any]) -> str:
    raw = (
        block.get("type")
        or block.get("block_type")
        or block.get("category_type")
        or block.get("category")
        or ""
    )
    value = str(raw).strip().lower().replace("-", "_")
    aliases = {
        "aside_text": "aside_text",
        "footer": "footer",
        "inline_equation": "equation",
        "interline_equation": "equation",
        "isolated_formula": "equation",
        "formula": "equation",
        "list": "list",
        "page_footnote": "page_footnote",
        "page_number": "page_number",
        "text": "text",
        "title": "text",
        "image": "image",
        "figure": "figure",
        "table": "table",
    }
    return aliases.get(value, value or "unknown")


_IGNORED_BLOCK_KINDS = {
    "aside_text",
    "footer",
    "list",
    "page_footnote",
    "page_number",
}


def _block_page(block: dict[str, Any]) -> int | None:
    for key in ("page_idx", "page_index"):
        if key in block:
            return _to_int(block.get(key), offset=1)
    for key in ("page", "page_number"):
        if key in block:
            return _to_int(block.get(key), offset=0)
    return None


def _to_int(value: Any, *, offset: int) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed + offset


def _block_pdf_rect(
    block: dict[str, Any],
    rects: dict[int, Any],
) -> tuple[float, float, float, float] | None:
    page = _block_page(block)
    page_rect = rects.get(page or -1)
    bbox = block.get("bbox") or block.get("poly") or block.get("polygon")
    if page_rect is None:
        return None
    return rect_to_pdf_points(bbox, page_rect=page_rect)


def _block_text(block: dict[str, Any]) -> str:
    return metadata_text(
        block.get("text")
        or block.get("content")
        or block.get("md_content")
    )


def _block_equation_text(block: dict[str, Any]) -> str:
    return metadata_text(
        block.get("latex")
        or block.get("text")
        or block.get("content")
        or block.get("md_content")
    )


def _block_text_level(block: dict[str, Any]) -> int | None:
    raw = block.get("text_level")
    if raw is None and str(block.get("type") or "").strip().lower() == "title":
        raw = 1
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return max(1, value)


def _block_caption(block: dict[str, Any]) -> str:
    return metadata_text(
        block.get("caption")
        or block.get("img_caption")
        or block.get("image_caption")
        or block.get("table_caption")
        or block.get("caption_text")
    )


def _table_rows(block: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    rows_value = block.get("table_rows") or block.get("rows")
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
    html = metadata_text(block.get("table_body") or block.get("html") or block.get("content"))
    if "<table" in html.lower():
        columns, rows = _html_table_rows(html)
        if columns or rows:
            return columns, rows
    if "|" in html:
        matrix = [
            [cell.strip() for cell in line.strip("|").split("|")]
            for line in html.splitlines()
            if "|" in line
        ]
        return _matrix_to_rows(matrix)
    return [], []


class _TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "tr":
            self._row = []
            return
        if tag in {"td", "th"} and self._row is not None:
            self._cell_parts = []
            self._in_cell = True

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self._row is not None and self._cell_parts is not None:
            self._row.append(_normalize_text(" ".join(self._cell_parts)))
            self._cell_parts = None
            self._in_cell = False
            return
        if tag == "tr" and self._row is not None:
            if any(cell for cell in self._row):
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._in_cell and self._cell_parts is not None:
            self._cell_parts.append(data)


def _html_table_rows(html: str) -> tuple[list[str], list[dict[str, Any]]]:
    parser = _TableHTMLParser()
    parser.feed(html)
    return _matrix_to_rows(parser.rows)


def _normalize_text(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    return re.sub(r"\s+([,.;:!?])", r"\1", normalized)


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


def _copy_block_asset(block: dict[str, Any], output_root: Path, target_dir: Path) -> str | None:
    raw = metadata_text(
        block.get("img_path")
        or block.get("image_path")
        or block.get("table_img_path")
    )
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
        "type",
        "page_idx",
        "page",
        "bbox",
        "text_level",
        "img_path",
        "image_path",
        "table_img_path",
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


__all__ = ["MinerUPdfDocumentParser"]
