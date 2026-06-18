from __future__ import annotations

import json
from typing import Any, Callable

import psycopg

from infrastructure.storage.postgres.dsn import normalize_dsn


ConnectionFactory = Callable[[], Any]

_INSERT_SQL = """
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


class PaperChunkRepository:
    """
    PostgreSQL payload repository for paper chunks. Implements ChunkPayloadRepositoryPort.
    Reads/writes payload dicts only — no domain-DTO dependency.
    """

    def __init__(self, dsn: str, *, connection_factory: ConnectionFactory | None = None) -> None:
        self._dsn = normalize_dsn(dsn)
        self._conn = connection_factory or (lambda: psycopg.connect(self._dsn))

    def save_payloads(self, payloads: list[dict[str, Any]]) -> None:
        if not payloads:
            return
        with self._conn() as conn:
            with conn.cursor() as cur:
                for p in payloads:
                    cur.execute(_INSERT_SQL, (
                        p["chunk_id"], p["paper_id"], p["chunk_type"],
                        p.get("section_title", ""),
                        json.dumps(list(p.get("section_role", []))),
                        p.get("section_index", 0), p["parse_source"], p.get("parent_chunk_id"),
                        p.get("has_formula", False), p.get("has_figure", False), p.get("has_table", False),
                        p.get("structure_detected", True),
                        p.get("propositions_generated", False),
                        p.get("proposition_quality", "unknown"),
                        json.dumps(list(p.get("references", []))),
                        p["content"],
                        json.dumps(p),
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
