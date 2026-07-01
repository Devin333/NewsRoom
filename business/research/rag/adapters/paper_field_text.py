from __future__ import annotations

from dataclasses import dataclass, field

from business.research.document.models import PaperChunk
from business.research.rag.formula_normalizer import normalize_formula_metadata

CORE_FIELD_NAMES: tuple[str, ...] = ("title", "abstract", "caption", "equation", "body")
EXPANDED_FIELD_NAMES: tuple[str, ...] = (
    "table_rows",
    "table_columns",
    "visual_description",
    "referenced_text",
)
FIELD_NAMES: tuple[str, ...] = (*CORE_FIELD_NAMES, *EXPANDED_FIELD_NAMES)


@dataclass(frozen=True)
class PaperChunkFieldText:
    title: str = ""
    abstract: str = ""
    caption: str = ""
    equation: str = ""
    body: str = ""
    table_rows: str = ""
    table_columns: str = ""
    visual_description: str = ""
    referenced_text: str = ""
    sources: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, str]:
        return {name: self.text_for(name) for name in FIELD_NAMES}

    def non_empty(self) -> dict[str, str]:
        return {name: text for name, text in self.as_dict().items() if text.strip()}

    def available_fields(self) -> tuple[str, ...]:
        return tuple(name for name, text in self.as_dict().items() if text.strip())

    def text_for(self, field_name: str) -> str:
        if field_name not in FIELD_NAMES:
            return ""
        return str(getattr(self, field_name))

    def sources_for(self, field_name: str) -> tuple[str, ...]:
        return tuple(self.sources.get(field_name, ()))


def extract_field_texts(chunk: PaperChunk) -> PaperChunkFieldText:
    title, title_sources = _title_text(chunk)
    abstract, abstract_sources = _abstract_text(chunk)
    caption, caption_sources = _caption_text(chunk)
    equation, equation_sources = _equation_text(chunk)
    body, body_sources = _body_text(chunk)
    table_rows, table_rows_sources = _table_rows_text(chunk)
    table_columns, table_columns_sources = _table_columns_text(chunk)
    visual_description, visual_description_sources = _visual_description_text(chunk)
    referenced_text, referenced_text_sources = _referenced_text(chunk)
    sources = {
        "title": tuple(title_sources),
        "abstract": tuple(abstract_sources),
        "caption": tuple(caption_sources),
        "equation": tuple(equation_sources),
        "body": tuple(body_sources),
        "table_rows": tuple(table_rows_sources),
        "table_columns": tuple(table_columns_sources),
        "visual_description": tuple(visual_description_sources),
        "referenced_text": tuple(referenced_text_sources),
    }
    return PaperChunkFieldText(
        title=title,
        abstract=abstract,
        caption=caption,
        equation=equation,
        body=body,
        table_rows=table_rows,
        table_columns=table_columns,
        visual_description=visual_description,
        referenced_text=referenced_text,
        sources={name: value for name, value in sources.items() if value},
    )


def _title_text(chunk: PaperChunk) -> tuple[str, list[str]]:
    text = _normalize_text(chunk.section_title)
    return text, ["section_title"] if text else []


def _abstract_text(chunk: PaperChunk) -> tuple[str, list[str]]:
    if chunk.chunk_type == "abstract" or chunk.section_title.casefold() == "abstract":
        text = _normalize_text(chunk.content)
        return text, ["content"] if text else []
    return "", []


def _caption_text(chunk: PaperChunk) -> tuple[str, list[str]]:
    values: list[tuple[str, str]] = [
        ("metadata.caption_text", str(chunk.metadata.get("caption_text") or "")),
        ("metadata.surya_caption", str(chunk.metadata.get("surya_caption") or "")),
    ]
    visual_description = str(chunk.metadata.get("visual_description") or "")
    if visual_description:
        values.append(("metadata.visual_description", visual_description))
    content_sources = chunk.metadata.get("content_sources", [])
    if chunk.chunk_type in {"figure", "table"} or "caption" in content_sources:
        values.append(("content.caption_block", _caption_block(chunk.content)))
    return _join_sourced_values(values)


def _equation_text(chunk: PaperChunk) -> tuple[str, list[str]]:
    formula_latex = chunk.formula_latex or (chunk.content if chunk.has_formula or chunk.chunk_type == "formula" else "")
    derived = normalize_formula_metadata(
        formula_latex,
        formula_description=chunk.formula_description,
        content=chunk.content,
        metadata=chunk.metadata,
    )
    values = [
        ("formula_latex", chunk.formula_latex),
        ("formula_description", chunk.formula_description),
        ("metadata.formula_normalized_latex", _metadata_or_derived(
            chunk.metadata.get("formula_normalized_latex"),
            derived.normalized_latex,
        )),
        ("metadata.formula_symbols", _metadata_or_derived(
            chunk.metadata.get("formula_symbols"),
            derived.symbols,
        )),
        ("metadata.formula_operators", _metadata_or_derived(
            chunk.metadata.get("formula_operators"),
            derived.operators,
        )),
        ("metadata.formula_structure_tokens", _metadata_or_derived(
            chunk.metadata.get("formula_structure_tokens"),
            derived.structure_tokens,
        )),
        ("metadata.formula_reference_labels", _metadata_or_derived(
            chunk.metadata.get("formula_reference_labels"),
            derived.reference_labels,
        )),
        ("metadata.formula_context_terms", _metadata_or_derived(
            chunk.metadata.get("formula_context_terms"),
            derived.context_terms,
        )),
        ("metadata.formula_referenced_text", _metadata_list_text(chunk.metadata.get("formula_referenced_text"))),
    ]
    if chunk.has_formula or chunk.chunk_type == "formula":
        values.append(("content", chunk.content))
    return _join_sourced_values(values)


def _body_text(chunk: PaperChunk) -> tuple[str, list[str]]:
    values = [("content", chunk.content)]
    if chunk.chunk_type == "table" or chunk.has_table or chunk.metadata.get("table_id"):
        values.extend([
            ("metadata.semantic_text", str(chunk.metadata.get("semantic_text") or "")),
            ("metadata.table_text", str(chunk.metadata.get("table_text") or "")),
            ("metadata.table_columns", _metadata_list_text(chunk.metadata.get("columns"))),
            ("metadata.table_rows", _metadata_rows_text(chunk.metadata.get("rows"))),
        ])
    visual_description = str(chunk.metadata.get("visual_description") or "")
    if visual_description and visual_description not in chunk.content:
        values.append(("metadata.visual_description", visual_description))
    return _join_sourced_values(values)


def _table_rows_text(chunk: PaperChunk) -> tuple[str, list[str]]:
    if not (chunk.chunk_type == "table" or chunk.has_table or chunk.metadata.get("table_id")):
        return "", []
    values = [
        ("metadata.rows", _metadata_rows_text(chunk.metadata.get("rows"))),
        ("metadata.table_rows", _metadata_rows_text(chunk.metadata.get("table_rows"))),
    ]
    return _join_sourced_values(values)


def _table_columns_text(chunk: PaperChunk) -> tuple[str, list[str]]:
    if not (chunk.chunk_type == "table" or chunk.has_table or chunk.metadata.get("table_id")):
        return "", []
    values = [
        ("metadata.columns", _metadata_list_text(chunk.metadata.get("columns"))),
        ("metadata.table_columns", _metadata_list_text(chunk.metadata.get("table_columns"))),
    ]
    return _join_sourced_values(values)


def _visual_description_text(chunk: PaperChunk) -> tuple[str, list[str]]:
    text = _normalize_text(str(chunk.metadata.get("visual_description") or ""))
    return text, ["metadata.visual_description"] if text else []


def _referenced_text(chunk: PaperChunk) -> tuple[str, list[str]]:
    values = [
        ("metadata.formula_referenced_text", _metadata_list_text(chunk.metadata.get("formula_referenced_text"))),
        ("metadata.referenced_text", _metadata_list_text(chunk.metadata.get("referenced_text"))),
        ("metadata.reference_text", _metadata_list_text(chunk.metadata.get("reference_text"))),
        ("metadata.referenced_by_chunks", _referenced_by_text(chunk.metadata.get("referenced_by_chunks"))),
    ]
    return _join_sourced_values(values)


def _join_sourced_values(values: list[tuple[str, str]]) -> tuple[str, list[str]]:
    parts: list[str] = []
    sources: list[str] = []
    seen_parts: set[str] = set()
    for source, raw in values:
        text = _normalize_text(raw)
        if not text or text in seen_parts:
            continue
        parts.append(text)
        sources.append(source)
        seen_parts.add(text)
    return "\n".join(parts), sources


def _caption_block(content: str) -> str:
    marker = "caption:"
    normalized = content.casefold()
    index = normalized.find(marker)
    if index < 0:
        return ""
    start = index + len(marker)
    tail = content[start:]
    lines: list[str] = []
    for line in tail.splitlines():
        stripped = line.strip()
        if not stripped:
            if lines:
                break
            continue
        if stripped.endswith(":") and lines:
            break
        lines.append(stripped)
    return " ".join(lines)


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").split())


def _metadata_list_text(value: object) -> str:
    if isinstance(value, list):
        return "\n".join(str(item) for item in value if str(item).strip())
    if isinstance(value, tuple):
        return "\n".join(str(item) for item in value if str(item).strip())
    return str(value or "")


def _metadata_or_derived(value: object, derived: object) -> str:
    text = _metadata_list_text(value)
    if text.strip():
        return text
    return _metadata_list_text(derived)


def _metadata_rows_text(value: object) -> str:
    if not isinstance(value, list):
        return str(value or "")
    rows: list[str] = []
    for row in value:
        if isinstance(row, dict):
            cells = [str(cell) for cell in row.values() if str(cell).strip()]
            if cells:
                rows.append(" | ".join(cells))
            continue
        text = str(row).strip()
        if text:
            rows.append(text)
    return "\n".join(rows)


def _referenced_by_text(value: object) -> str:
    if not isinstance(value, list):
        return ""
    texts: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("text_ref") or item.get("snippet") or "").strip()
            if text:
                texts.append(text)
    return "\n".join(texts)


__all__ = [
    "CORE_FIELD_NAMES",
    "EXPANDED_FIELD_NAMES",
    "FIELD_NAMES",
    "PaperChunkFieldText",
    "extract_field_texts",
]
