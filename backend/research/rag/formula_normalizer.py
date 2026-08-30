from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


_LAYOUT_COMMAND_RE = re.compile(
    r"\\(?:left|right|quad|qquad|thinspace|medspace|thickspace)\b|\\[,;:!]"
)
_LABEL_RE = re.compile(r"\\(?:label|tag)\{([^{}]+)\}")
_OPERATORNAME_RE = re.compile(r"\\operatorname\{([^{}]+)\}")
_COMMAND_RE = re.compile(r"\\([A-Za-z]+)")
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*|[0-9]+")
_REFERENCE_TEXT_RE = re.compile(r"\b(?:equation|eq\.?|formula)\s*\(?([A-Za-z0-9_.:-]+)\)?", re.IGNORECASE)

_KNOWN_OPERATORS = {
    "argmax",
    "argmin",
    "cos",
    "det",
    "exp",
    "log",
    "max",
    "mean",
    "min",
    "prod",
    "sin",
    "softmax",
    "sqrt",
    "sum",
    "tan",
    "trace",
    "var",
}
_GREEK_SYMBOLS = {
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "varepsilon",
    "zeta",
    "eta",
    "theta",
    "vartheta",
    "iota",
    "kappa",
    "lambda",
    "mu",
    "nu",
    "xi",
    "pi",
    "rho",
    "sigma",
    "tau",
    "upsilon",
    "phi",
    "varphi",
    "chi",
    "psi",
    "omega",
}
_NON_SYMBOL_COMMANDS = {
    "begin",
    "end",
    "frac",
    "left",
    "right",
    "quad",
    "qquad",
    "thinspace",
    "medspace",
    "thickspace",
    "label",
    "tag",
    "operatorname",
    "text",
    "mathrm",
    "mathbf",
    "mathbb",
    "mathcal",
    "mathit",
    "sqrt",
}
_CONTEXT_STOP_WORDS = {
    "and",
    "are",
    "for",
    "from",
    "into",
    "latex",
    "the",
    "this",
    "that",
    "with",
    "where",
}


@dataclass(frozen=True)
class FormulaRetrievalMetadata:
    raw_latex: str = ""
    normalized_latex: str = ""
    symbols: tuple[str, ...] = ()
    operators: tuple[str, ...] = ()
    structure_tokens: tuple[str, ...] = ()
    reference_labels: tuple[str, ...] = ()
    context_terms: tuple[str, ...] = ()

    def as_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        if self.raw_latex:
            metadata["formula_latex_raw"] = self.raw_latex
        if self.normalized_latex:
            metadata["formula_normalized_latex"] = self.normalized_latex
        if self.symbols:
            metadata["formula_symbols"] = list(self.symbols)
        if self.operators:
            metadata["formula_operators"] = list(self.operators)
        if self.structure_tokens:
            metadata["formula_structure_tokens"] = list(self.structure_tokens)
        if self.reference_labels:
            metadata["formula_reference_labels"] = list(self.reference_labels)
        if self.context_terms:
            metadata["formula_context_terms"] = list(self.context_terms)
        return metadata


def normalize_formula_metadata(
    formula_latex: str,
    *,
    formula_description: str = "",
    content: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> FormulaRetrievalMetadata:
    raw_latex = str(formula_latex or "").strip()
    raw_context = "\n".join(value for value in (formula_description, content) if str(value or "").strip())
    existing = metadata or {}
    labels = _reference_labels(raw_latex, content, existing)
    operators = _operators(raw_latex)
    symbols = _symbols(raw_latex, operators)
    normalized = _normalized_latex(raw_latex)
    structure_tokens = _structure_tokens(raw_latex)
    context_terms = _context_terms(raw_context)
    return FormulaRetrievalMetadata(
        raw_latex=raw_latex,
        normalized_latex=normalized,
        symbols=tuple(symbols),
        operators=tuple(operators),
        structure_tokens=tuple(structure_tokens),
        reference_labels=tuple(labels),
        context_terms=tuple(context_terms),
    )


def enrich_formula_metadata(
    base_metadata: Mapping[str, Any] | None,
    *,
    formula_latex: str,
    formula_description: str = "",
    content: str = "",
) -> dict[str, Any]:
    metadata = dict(base_metadata or {})
    derived = normalize_formula_metadata(
        formula_latex,
        formula_description=formula_description,
        content=content,
        metadata=metadata,
    )
    for key, value in derived.as_metadata().items():
        if _metadata_has_value(metadata.get(key)):
            metadata[key] = _merge_metadata_values(metadata[key], value)
        else:
            metadata[key] = value
    return metadata


def formula_query_terms(text: str) -> FormulaRetrievalMetadata:
    return normalize_formula_metadata(str(text or ""), content=str(text or ""))


def _normalized_latex(latex: str) -> str:
    text = str(latex or "")
    text = _LABEL_RE.sub(" ", text)
    text = _OPERATORNAME_RE.sub(lambda match: f" {match.group(1).casefold()} ", text)
    text = _LAYOUT_COMMAND_RE.sub(" ", text)
    text = re.sub(r"\\(?:mathrm|mathbf|mathit|text|mathcal|mathbb)\{([^{}]+)\}", r"\1", text)
    text = re.sub(r"\\([A-Za-z]+)", lambda match: f" {match.group(1).casefold()} ", text)
    text = re.sub(r"_\{([^{}]+)\}", r"_\1", text)
    text = re.sub(r"\^\{([^{}]+)\}", r"^\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().casefold()


def _operators(latex: str) -> list[str]:
    values: list[str] = []
    values.extend(match.group(1).strip().casefold() for match in _OPERATORNAME_RE.finditer(str(latex or "")))
    for command in _COMMAND_RE.findall(str(latex or "")):
        lowered = command.casefold()
        if lowered in _KNOWN_OPERATORS:
            values.append(lowered)
    return _unique(values)


def _symbols(latex: str, operators: Iterable[str]) -> list[str]:
    operator_set = {operator.casefold() for operator in operators}
    values: list[str] = []
    for command in _COMMAND_RE.findall(str(latex or "")):
        lowered = command.casefold()
        if lowered in _GREEK_SYMBOLS:
            values.append(lowered)
        elif lowered not in _NON_SYMBOL_COMMANDS and lowered not in _KNOWN_OPERATORS:
            values.append(lowered)
    stripped = _OPERATORNAME_RE.sub(" ", str(latex or ""))
    stripped = re.sub(r"\\(?:label|tag|text|mathrm|mathbf|mathit|mathcal|mathbb)\{[^{}]*\}", " ", stripped)
    stripped = re.sub(r"\\[A-Za-z]+", " ", stripped)
    stripped = re.sub(r"_\{([^{}]+)\}", r"_\1", stripped)
    for token in _TOKEN_RE.findall(stripped):
        token = token.strip()
        lowered = token.casefold()
        if not token or lowered in operator_set or lowered in _KNOWN_OPERATORS or lowered in _NON_SYMBOL_COMMANDS:
            continue
        if len(token) == 1 or "_" in token or token[:1].isupper() or any(char.isdigit() for char in token):
            values.append(token)
    return _unique(values)


def _structure_tokens(latex: str) -> list[str]:
    text = str(latex or "")
    tokens: list[str] = []
    if r"\frac" in text or "/" in text:
        tokens.append("fraction")
    if r"\sqrt" in text:
        tokens.append("sqrt")
    if r"\sum" in text:
        tokens.append("summation")
    if r"\prod" in text:
        tokens.append("product")
    if r"\int" in text:
        tokens.append("integral")
    if re.search(r"\\begin\{(?:[pbvBV]?matrix|array|aligned|cases)\}", text):
        tokens.append("matrix")
    if "_" in text:
        tokens.append("subscript")
    if "^" in text:
        tokens.append("superscript")
    if re.search(r"\^[{\s]*(?:T|\\top)", text):
        tokens.append("transpose")
    if "=" in text:
        tokens.append("equality")
    if any(marker in text for marker in ("<", ">", r"\le", r"\ge", r"\neq")):
        tokens.append("inequality")
    if _OPERATORNAME_RE.search(text) or re.search(r"[A-Za-z][A-Za-z0-9_]*\s*\(", text):
        tokens.append("function_call")
    if any(marker in text for marker in (r"\times", r"\cdot", r"\top", "^T")):
        tokens.append("matrix_multiply")
    return _unique(tokens)


def _reference_labels(latex: str, content: str, metadata: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for source in (latex, content):
        values.extend(match.group(1).strip() for match in _LABEL_RE.finditer(str(source or "")))
        values.extend(match.group(1).strip() for match in _REFERENCE_TEXT_RE.finditer(str(source or "")))
    for key in ("reference_labels", "equation_id", "equation_label", "element_label"):
        values.extend(_metadata_values(metadata.get(key)))
    return _unique(values)


def _context_terms(text: str) -> list[str]:
    terms = [
        token.casefold()
        for token in _TOKEN_RE.findall(str(text or ""))
        if len(token) > 2 and token.casefold() not in _CONTEXT_STOP_WORDS
    ]
    return _unique(terms)[:24]


def _metadata_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _metadata_has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return True


def _merge_metadata_values(existing: Any, derived: Any) -> Any:
    if isinstance(derived, list):
        return _unique([*_metadata_values(existing), *_metadata_values(derived)])
    if isinstance(derived, str):
        return str(existing or derived)
    return existing if _metadata_has_value(existing) else derived


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out
