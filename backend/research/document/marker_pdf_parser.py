from __future__ import annotations

import base64
import binascii
import json
import os
import re
import shutil
import time
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

from backend.foundation import build_stable_id
from backend.research.document.docker_pdf_parser import (
    first_existing_file,
    metadata_text,
    page_rects,
    rect_to_pdf_points,
    run_docker_command,
    safe_paper_id,
    source_locator,
    stage_pdf_for_docker,
)
from backend.research.domain.common import SourceLineage
from backend.research.domain.document import (
    ResearchDocument,
    ResearchEquation,
    ResearchFigure,
    ResearchSection,
    ResearchTable,
)


class MarkerPdfDocumentParser:
    """Docker-backed Marker parser for PDF parser bake-off and cascade use."""

    def __init__(self, *, command_runner: Callable[..., Any] | None = None) -> None:
        self._command_runner = command_runner or run_docker_command

    def parse(
        self,
        paper_id: str,
        source_bytes: bytes,
        *,
        execution_identity: Any | None = None,
    ) -> ResearchDocument:
        source_hash = sha256(source_bytes).hexdigest()
        source_ref = f"arxiv://{paper_id}/pdf"
        started_at = time.perf_counter()
        input_dir, output_dir, _pdf_path = stage_pdf_for_docker(
            backend="marker",
            paper_id=paper_id,
            pdf_bytes=source_bytes,
        )
        command = _marker_command(input_dir=input_dir, output_dir=output_dir)
        runner_kwargs: dict[str, Any] = {
            "timeout_seconds": _marker_timeout_seconds(),
        }
        if self._command_runner is not run_docker_command:
            runner_kwargs.update(
                execution_identity=execution_identity,
                paper_id=paper_id,
                backend="marker",
            )
        outcome = self._command_runner(command, **runner_kwargs)
        document = _document_from_marker_output(
            paper_id=paper_id,
            source_ref=source_ref,
            source_hash=source_hash,
            pdf_bytes=source_bytes,
            output_dir=output_dir,
            duration_seconds=time.perf_counter() - started_at,
            command=command,
        )
        return _with_execution_receipt(document, outcome)


def _with_execution_receipt(document: ResearchDocument, outcome: Any) -> ResearchDocument:
    receipt = getattr(outcome, "receipt", None)
    if receipt is None:
        return document
    return document.model_copy(
        update={
            "metadata": {
                **dict(document.metadata),
                "execution_receipt_ref": f"execution-receipt://{receipt.execution_id}",
                "execution_receipt_checksum": receipt.receipt_checksum,
                "execution_provider": receipt.provider_id,
                "execution_status": receipt.status.value,
            }
        }
    )


def _marker_command(*, input_dir: Path, output_dir: Path) -> list[str]:
    image = os.environ.get("NEWSROOM_MARKER_DOCKER_IMAGE", "newsroom-marker:latest").strip()
    extra_args = _split_env_args(os.environ.get("NEWSROOM_MARKER_DOCKER_ARGS", ""))
    cache_dir = os.environ.get("NEWSROOM_MARKER_CACHE_DIR", "").strip()
    return [
        "docker",
        "run",
        "--rm",
        "--gpus",
        "all",
        "-e",
        "TORCH_DEVICE=cuda",
        "-e",
        "HF_HOME=/root/.cache/huggingface",
        *extra_args,
        *(
            [
                "-v",
                f"{Path(cache_dir).resolve()}:/root/.cache",
            ]
            if cache_dir
            else []
        ),
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
    markdown_path = _marker_markdown_path(output_dir)
    rects = page_rects(pdf_bytes)
    artifact_root = _paper_artifact_dir(paper_id)
    figures_dir = artifact_root / "figures"
    tables_dir = artifact_root / "tables"
    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    if json_path is not None:
        blocks = _load_marker_blocks(json_path)
        components = _components_from_blocks(
            paper_id=paper_id,
            source_ref=source_ref,
            blocks=blocks,
            page_rects_by_number=rects,
            output_root=json_path.parent,
            figures_dir=figures_dir,
            tables_dir=tables_dir,
            warnings=warnings,
        )
        parser_content_ref = str(json_path)
    elif markdown_path is not None:
        components = _components_from_markdown(
            paper_id=paper_id,
            source_ref=source_ref,
            markdown=markdown_path.read_text(encoding="utf-8"),
        )
        parser_content_ref = str(markdown_path)
        warnings.append("json artifact missing; parsed markdown fallback")
    else:
        raise FileNotFoundError(f"Marker did not produce JSON or Markdown output under {output_dir}")

    metadata = {
        "parse_source": "marker",
        "parser_backend": "marker",
        "parser_output_ref": str(output_dir),
        "parser_content_ref": parser_content_ref,
        "parser_duration_seconds": round(duration_seconds, 3),
        "parser_command": _redacted_command(command),
        "parser_warnings": warnings,
        "parse_quality": _parse_quality(
            components.sections,
            components.figures,
            components.tables,
            components.equations,
        ),
    }
    return ResearchDocument(
        paper_id=paper_id,
        source_hash=source_hash,
        sections=components.sections,
        figures=components.figures,
        tables=components.tables,
        equations=components.equations,
        lineage=SourceLineage(source_refs=[source_ref], source_hash=source_hash),
        metadata=metadata,
    )


class _Components:
    def __init__(self) -> None:
        self.sections: list[ResearchSection] = []
        self.figures: list[ResearchFigure] = []
        self.tables: list[ResearchTable] = []
        self.equations: list[ResearchEquation] = []


def _marker_json_path(output_dir: Path) -> Path | None:
    direct = first_existing_file(
        output_dir,
        (
            "input.json",
            "input_meta.json",
            "input_content.json",
            "output.json",
            "document.json",
        ),
    )
    if direct is not None:
        return direct
    candidates = [
        path for path in output_dir.rglob("*.json")
        if path.is_file() and not path.name.startswith(".")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda path: (path.name.endswith("_meta.json"), len(path.parts), path.name))
    return candidates[0]


def _marker_markdown_path(output_dir: Path) -> Path | None:
    return first_existing_file(output_dir, ("input.md", "output.md", "document.md"))


def _load_marker_blocks(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    blocks = _extract_blocks(payload)
    if not blocks:
        raise ValueError(f"Marker JSON did not contain parse blocks: {path}")
    return blocks


def _extract_blocks(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("blocks", "children", "items", "content", "pages"):
        value = payload.get(key)
        if isinstance(value, list):
            if key == "pages":
                return _flatten_pages(value)
            return _flatten_blocks(value)
    if any(key in payload for key in ("text", "html", "markdown", "block_type", "type")):
        return [payload]
    return []


def _flatten_pages(pages: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for page_index, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            continue
        raw_blocks = page.get("blocks") or page.get("children") or page.get("items") or []
        if not isinstance(raw_blocks, list):
            continue
        page_number = _page_number(page, default=page_index)
        for block in _flatten_blocks(raw_blocks):
            block.setdefault("page", page_number)
            out.append(block)
    return out


def _flatten_blocks(blocks: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in blocks:
        if not isinstance(item, dict):
            continue
        out.append(item)
        children = item.get("children") or item.get("blocks") or item.get("items")
        if isinstance(children, list):
            for child in _flatten_blocks(children):
                child.setdefault("page", _page_number(item, default=None))
                child.setdefault("_marker_parent_kind", _block_kind(item))
                out.append(child)
    return out


def _components_from_blocks(
    *,
    paper_id: str,
    source_ref: str,
    blocks: list[dict[str, Any]],
    page_rects_by_number: dict[int, Any],
    output_root: Path,
    figures_dir: Path,
    tables_dir: Path,
    warnings: list[str],
) -> _Components:
    components = _Components()
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
        components.sections.append(ResearchSection(
            section_id=build_stable_id("sec", paper_id, "marker", current_title, str(section_index)),
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
        if _is_group_child_element(block):
            continue
        page = _page_number(block, default=current_page)
        pdf_rect = _block_pdf_rect(block, page_rects_by_number)
        locator = source_locator(source_ref, page=page, pdf_rect=pdf_rect)
        if kind == "heading":
            text = _block_text(block)
            if not text:
                continue
            flush_section()
            current_title = text[:160]
            current_level = _heading_level(block)
            current_page = page
            continue
        if kind == "text":
            text = _block_text(block)
            if not text:
                continue
            if current_page is None:
                current_page = page
            current_parts.append(text)
            continue
        if kind == "equation":
            latex = _block_equation_text(block)
            if latex:
                components.equations.append(ResearchEquation(
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
        if kind == "figure":
            caption = _block_caption(block) or f"Figure from page {page or '?'}"
            image_ref = _copy_block_asset(block, output_root, figures_dir)
            components.figures.append(ResearchFigure(
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
        if kind == "table":
            caption = _block_caption(block) or f"Table from page {page or '?'}"
            columns, rows = _table_rows(block)
            image_ref = _copy_block_asset(block, output_root, tables_dir)
            components.tables.append(ResearchTable(
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
        if kind in _IGNORED_BLOCK_KINDS:
            continue
        warnings.append(f"block_{index}: unsupported Marker type {kind!r}")

    flush_section()
    if not components.sections:
        text = "\n\n".join(_block_text(block) for block in blocks if _block_text(block)).strip()
        if text:
            locator = source_locator(source_ref, page=None)
            components.sections.append(ResearchSection(
                section_id=build_stable_id("sec", paper_id, "marker", "fallback"),
                title="Document",
                level=1,
                text=text,
                source_ref=locator,
                metadata={"parse_source": "marker", "source_locator": locator},
            ))
    return components


def _components_from_markdown(*, paper_id: str, source_ref: str, markdown: str) -> _Components:
    components = _Components()
    matches = list(_MARKDOWN_HEADING_RE.finditer(markdown))
    preamble = markdown[: matches[0].start()].strip() if matches else markdown.strip()
    if preamble:
        components.sections.append(ResearchSection(
            section_id=build_stable_id("sec", paper_id, "marker", "preamble"),
            title="Document",
            level=1,
            text=preamble,
            source_ref=source_ref,
            metadata={"parse_source": "marker", "source_locator": source_ref},
        ))
    for index, match in enumerate(matches):
        title = match.group(2).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = markdown[start:end].strip()
        if not body:
            continue
        components.sections.append(ResearchSection(
            section_id=build_stable_id("sec", paper_id, "marker", title, str(index)),
            title=title,
            level=len(match.group(1)),
            text=body,
            source_ref=source_ref,
            metadata={"parse_source": "marker", "source_locator": source_ref},
        ))
    return components


_MARKDOWN_HEADING_RE = re.compile(r"(?m)^(#{1,6})\s+(.+?)\s*$")


def _block_kind(block: dict[str, Any]) -> str:
    raw = (
        block.get("type")
        or block.get("block_type")
        or block.get("blockType")
        or block.get("category")
        or ""
    )
    value = str(raw).strip().lower().replace("-", "_")
    aliases = {
        "caption": "caption",
        "code": "text",
        "document": "ignored",
        "equation": "equation",
        "figure": "figure",
        "figuregroup": "figure",
        "form": "ignored",
        "handwriting": "text",
        "heading": "heading",
        "image": "figure",
        "line": "text",
        "list": "text",
        "listgroup": "text",
        "page": "ignored",
        "pagefooter": "ignored",
        "pageheader": "ignored",
        "pagenumber": "ignored",
        "picture": "figure",
        "picturegroup": "figure",
        "sectionheader": "heading",
        "table": "table",
        "tablegroup": "table",
        "tableofcontents": "ignored",
        "text": "text",
        "textinlineequation": "text",
        "textinlinemath": "text",
        "title": "heading",
    }
    return aliases.get(value, value or "text")


_IGNORED_BLOCK_KINDS = {"caption", "ignored", "pagefooter", "pageheader", "pagenumber"}


def _is_group_child_element(block: dict[str, Any]) -> bool:
    kind = _block_kind(block)
    parent_kind = metadata_text(block.get("_marker_parent_kind"))
    if parent_kind == "table" and kind == "table":
        return True
    if parent_kind == "figure" and kind == "figure":
        return True
    return False


def _page_number(block: dict[str, Any], default: int | None = None) -> int | None:
    for key in ("page", "page_number"):
        if key in block:
            return _to_int(block.get(key), offset=0)
    for key in ("page_idx", "page_id", "page_index"):
        if key in block:
            return _to_int(block.get(key), offset=1)
    page = _page_from_marker_id(metadata_text(block.get("id")))
    if page is not None:
        return page
    return default


_MARKER_PAGE_ID_RE = re.compile(r"(?:^|/)page/(\d+)(?:/|$)", re.IGNORECASE)


def _page_from_marker_id(value: str) -> int | None:
    match = _MARKER_PAGE_ID_RE.search(value)
    if not match:
        return None
    return int(match.group(1)) + 1


def _to_int(value: Any, *, offset: int) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed + offset


def _heading_level(block: dict[str, Any]) -> int:
    for key in ("heading_level", "level", "text_level"):
        try:
            return max(1, int(block[key]))
        except (KeyError, TypeError, ValueError):
            continue
    return 1


def _block_pdf_rect(
    block: dict[str, Any],
    rects: dict[int, Any],
) -> tuple[float, float, float, float] | None:
    page = _page_number(block)
    page_rect = rects.get(page or -1)
    bbox = (
        block.get("bbox")
        or block.get("box")
        or block.get("polygon")
        or block.get("poly")
    )
    if page_rect is None:
        return None
    return rect_to_pdf_points(bbox, page_rect=page_rect)


def _block_text(block: dict[str, Any]) -> str:
    return _html_to_text(metadata_text(
        block.get("text")
        or block.get("content")
        or block.get("html")
        or block.get("markdown")
        or block.get("md")
    ))


def _block_equation_text(block: dict[str, Any]) -> str:
    return _html_to_text(metadata_text(
        block.get("latex")
        or block.get("tex")
        or block.get("text")
        or block.get("content")
        or block.get("html")
    ))


def _block_caption(block: dict[str, Any]) -> str:
    direct = metadata_text(
        block.get("caption")
        or block.get("caption_text")
        or block.get("image_caption")
        or block.get("table_caption")
    )
    if direct:
        return _strip_caption_prefix(direct)
    children = block.get("children") or block.get("blocks") or []
    if isinstance(children, list):
        for child in children:
            if not isinstance(child, dict):
                continue
            if _block_kind(child) == "caption":
                text = _block_text(child)
                if text:
                    return _strip_caption_prefix(text)
    return ""


def _strip_caption_prefix(value: str) -> str:
    return _html_to_text(value)


def _table_rows(block: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    for table_block in _candidate_table_blocks(block):
        rows_value = table_block.get("table_rows") or table_block.get("rows")
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
        html = metadata_text(
            table_block.get("html")
            or table_block.get("table_html")
            or table_block.get("table_body")
            or table_block.get("content")
        )
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


def _candidate_table_blocks(block: dict[str, Any]) -> list[dict[str, Any]]:
    out = [block] if _block_kind(block) == "table" else []
    for child in _block_children(block):
        if _block_kind(child) == "table":
            out.append(child)
    return out or [block]


def _block_children(block: dict[str, Any]) -> list[dict[str, Any]]:
    children = block.get("children") or block.get("blocks") or block.get("items") or []
    if not isinstance(children, list):
        return []
    return [child for child in children if isinstance(child, dict)]


class _TextHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"br", "p", "div", "tr"}:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"p", "div", "tr", "table"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _html_to_text(value: str) -> str:
    if not value:
        return ""
    if "<" not in value or ">" not in value:
        return _normalize_text(value)
    parser = _TextHTMLParser()
    parser.feed(value)
    return _normalize_text(" ".join(parser.parts))


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
    for asset_block in _candidate_asset_blocks(block):
        raw = metadata_text(
            asset_block.get("image_path")
            or asset_block.get("img_path")
            or asset_block.get("path")
            or asset_block.get("file_path")
            or asset_block.get("table_img_path")
        )
        if raw:
            copied = _copy_marker_path_asset(raw, output_root, target_dir)
            if copied:
                return copied
        for name, raw_image in _iter_marker_images(asset_block):
            written = _write_base64_marker_image(
                raw_image,
                target_dir=target_dir,
                stem=safe_paper_id(name or metadata_text(asset_block.get("id")) or "marker_image"),
            )
            if written:
                return written
            copied = _copy_marker_path_asset(metadata_text(raw_image), output_root, target_dir)
            if copied:
                return copied
    return None


def _candidate_asset_blocks(block: dict[str, Any]) -> list[dict[str, Any]]:
    out = [block]
    out.extend(_block_children(block))
    return out


def _iter_marker_images(block: dict[str, Any]) -> list[tuple[str, Any]]:
    images = block.get("images")
    if isinstance(images, dict):
        return [(metadata_text(key), value) for key, value in images.items()]
    if isinstance(images, list):
        return [(f"image_{index}", value) for index, value in enumerate(images)]
    return []


def _copy_marker_path_asset(raw: str, output_root: Path, target_dir: Path) -> str | None:
    if not raw or _looks_like_base64(raw):
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


def _write_base64_marker_image(raw: Any, *, target_dir: Path, stem: str) -> str | None:
    value = metadata_text(raw)
    if not _looks_like_base64(value):
        return None
    image_bytes, suffix = _decode_base64_image(value)
    if not image_bytes:
        return None
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{stem}{suffix}"
    target.write_bytes(image_bytes)
    return str(target)


def _looks_like_base64(value: str) -> bool:
    if value.startswith("data:image/"):
        return True
    compact = re.sub(r"\s+", "", value)
    if len(compact) < 24:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", compact))


def _decode_base64_image(value: str) -> tuple[bytes | None, str]:
    suffix = ".jpg"
    payload = value.strip()
    if payload.startswith("data:image/"):
        header, _, payload = payload.partition(",")
        media = header.removeprefix("data:").split(";", 1)[0]
        suffix = _image_suffix_for_media_type(media)
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        return None, suffix
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        suffix = ".png"
    elif data.startswith(b"\xff\xd8\xff"):
        suffix = ".jpg"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        suffix = ".webp"
    return data, suffix


def _image_suffix_for_media_type(media_type: str) -> str:
    return {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(media_type.lower(), ".jpg")


def _paper_artifact_dir(paper_id: str) -> Path:
    root = Path(os.environ.get("NEWS_ARTIFACT_ROOT", ".newsroom/runs"))
    return root.parent / "papers" / paper_id


def _compact_block_metadata(block: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "type",
        "block_type",
        "page",
        "page_idx",
        "page_id",
        "bbox",
        "box",
        "polygon",
        "heading_level",
        "level",
        "image_path",
        "img_path",
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
            "with_page": sum(1 for item in figures if item.page is not None),
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
            "with_page": sum(1 for item in equations if item.page is not None),
            "with_bbox": sum(1 for item in equations if item.metadata.get("pdf_rect")),
            "with_source_locator": sum(1 for item in equations if item.metadata.get("source_locator")),
        },
    }


def _redacted_command(command: list[str]) -> list[str]:
    return [
        "<repo-path>"
        if any(marker in part for marker in ("NewsRoom", "Agora-Hub", "Agora Hub"))
        else part
        for part in command
    ]


__all__ = ["MarkerPdfDocumentParser"]
