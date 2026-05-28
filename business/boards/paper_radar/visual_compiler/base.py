from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from business.boards.paper_radar.visual_compiler.models import PaperAssetManifest, PaperCompileInfo, PaperDocument


@dataclass(frozen=True)
class PaperCompileDraft:
    document: PaperDocument
    manifest: PaperAssetManifest
    compile_info: PaperCompileInfo


class PaperCompilerError(RuntimeError):
    def __init__(self, message: str, *, code: str, diagnostics: Sequence[Mapping[str, object]] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostics = tuple(dict(item) for item in diagnostics)


class PaperCompiler(Protocol):
    def compile(
        self,
        *,
        pdf_bytes: bytes,
        paper: Mapping[str, Any],
        output_dir: Path,
        source_pdf_url: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
    ) -> PaperCompileDraft:
        ...

    def render_source_preview(self, **kwargs: Any) -> Path:
        ...
