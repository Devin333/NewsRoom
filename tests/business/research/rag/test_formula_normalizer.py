from __future__ import annotations

from business.research.rag.formula_normalizer import normalize_formula_metadata


def test_normalize_formula_metadata_extracts_stable_formula_terms() -> None:
    metadata = normalize_formula_metadata(
        r"\label{eq:attn}\operatorname{Attention}(Q,K,V)=\operatorname{softmax}"
        r"\left(\frac{QK^T}{\sqrt{d_k}}\right)V",
        formula_description="Attention maps queries keys and values.",
        content="Equation 2 defines the attention mechanism.",
        metadata={"reference_labels": ["2"]},
    )

    assert metadata.raw_latex.startswith(r"\label{eq:attn}")
    assert "label" not in metadata.normalized_latex
    assert "left" not in metadata.normalized_latex
    assert {"Q", "K", "V", "d_k"}.issubset(set(metadata.symbols))
    assert {"attention", "softmax", "sqrt"}.issubset(set(metadata.operators))
    assert {"fraction", "sqrt", "superscript", "transpose", "function_call"}.issubset(
        set(metadata.structure_tokens)
    )
    assert {"eq:attn", "2"}.issubset(set(metadata.reference_labels))
    assert "queries" in metadata.context_terms


def test_normalize_formula_metadata_keeps_greek_symbols() -> None:
    metadata = normalize_formula_metadata(
        r"\alpha_t = \lambda \sum_i x_i",
        formula_description="Alpha and lambda control the weighted sum.",
    )

    assert {"alpha", "lambda"}.issubset(set(metadata.symbols))
    assert "sum" in metadata.operators
    assert "summation" in metadata.structure_tokens


def test_normalize_formula_metadata_keeps_math_commands_but_drops_layout_commands() -> None:
    metadata = normalize_formula_metadata(
        r"\Omega \mapsto \partial_x f \qquad \forall x \in \mathbb{R}",
        formula_description="The mapping uses a partial derivative.",
    )

    assert {"omega", "mapsto", "partial", "forall"}.issubset(set(metadata.symbols))
    assert "qquad" not in metadata.symbols
    assert "qquad" not in metadata.normalized_latex
