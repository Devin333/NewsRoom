from __future__ import annotations

import json
from typing import Any, Callable

import psycopg

from business.research.document.models import PaperChunk


ConnectionFactory = Callable[[], Any]


class PaperChunkRepository:
    def __init__(self, dsn: str, *, connection_factory: ConnectionFactory | None = None) -> None:
        self._dsn = dsn
        self._conn = connection_factory or (lambda: psycopg.connect(dsn))

    def save_chunks(self, chunks: list[PaperChunk]) -> None:
        if not chunks:
            return
        sql = """
        INSERT INTO paper_chunks (
            chunk_id, paper_id, chunk_type, section_title, section_role,
            section_index, parse_source, parent_chunk_id,
            has_formula, has_figure, has_table,
            structure_detected, propositions_generated, proposition_quality,
            references_json, content, payload
        )
        VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb)
        ON CONFLICT (chunk_id) DO UPDATE SET
            section_role        = EXCLUDED.section_role,
            propositions_generated = EXCLUDED.propositions_generated,
            proposition_quality = EXCLUDED.proposition_quality,
            payload             = EXCLUDED.payload,
            updated_at          = now()
        """
        with self._conn() as conn:
            with conn.cursor() as cur:
                for c in chunks:
                    cur.execute(sql, (
                        c.chunk_id, c.paper_id, c.chunk_type,
                        c.section_title,
                        json.dumps(list(c.section_role)),
                        c.section_index, c.parse_source, c.parent_chunk_id,
                        c.has_formula, c.has_figure, c.has_table,
                        c.structure_detected, c.propositions_generated, c.proposition_quality,
                        json.dumps(list(c.references)),
                        c.content,
                        json.dumps(c.model_dump(mode="json")),
                    ))
            conn.commit()

    def list_paper_chunks(self, paper_id: str) -> list[dict[str, Any]]:
        sql = "SELECT payload FROM paper_chunks WHERE paper_id = %s ORDER BY section_index, chunk_id"
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (paper_id,))
                return [row[0] for row in cur.fetchall()]

    def delete_paper_chunks(self, paper_id: str) -> None:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM paper_chunks WHERE paper_id = %s", (paper_id,))
            conn.commit()


__all__ = ["PaperChunkRepository"]
