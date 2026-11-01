"""Business knowledge persistence backed by PostgreSQL + pgvector."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

from psycopg.types.json import Jsonb

from ...database import get_pg_pool, setup_database

SEED_PATH = Path(__file__).parent / "seed" / "procurement_knowledge.json"


@dataclass
class KnowledgeDoc:
    id: str
    title: str
    content: str
    domain: str  # procurement_sop | avl | material_spec | exception
    source: str
    version: str
    tags: list[str] = field(default_factory=list)
    part_codes: list[str] = field(default_factory=list)
    supplier_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class KnowledgeStore:
    def __init__(self, docs: Optional[list[KnowledgeDoc]] = None):
        self._docs = {doc.id: doc for doc in docs or []}

    def upsert(self, doc: KnowledgeDoc) -> None:
        self._docs[doc.id] = doc

    def get(self, doc_id: str) -> Optional[KnowledgeDoc]:
        return self._docs.get(doc_id)

    def all(self) -> list[KnowledgeDoc]:
        return list(self._docs.values())

    def filter(
        self,
        *,
        domain: Optional[str] = None,
        part_code: Optional[str] = None,
        supplier_code: Optional[str] = None,
    ) -> list[KnowledgeDoc]:
        rows = self.all()
        if domain:
            rows = [d for d in rows if d.domain == domain]
        if part_code:
            code = part_code.upper()
            rows = [d for d in rows if code in [c.upper() for c in d.part_codes] or code in d.content.upper()]
        if supplier_code:
            code = supplier_code.upper()
            rows = [
                d
                for d in rows
                if code in [c.upper() for c in d.supplier_codes] or code in d.content.upper()
            ]
        return rows

    def load_json(self, path: Path) -> int:
        docs = [
            KnowledgeDoc(**row)
            for row in json.loads(path.read_text(encoding="utf-8"))
        ]
        self._docs.update({doc.id: doc for doc in docs})
        return len(docs)


class PostgresKnowledgeStore(KnowledgeStore):
    """Unified runtime knowledge store; no second vector database is required."""

    def __init__(self) -> None:
        setup_database()
        self.pool = get_pg_pool()

    @staticmethod
    def _row_to_doc(row: dict[str, Any]) -> KnowledgeDoc:
        return KnowledgeDoc(
            id=str(row["id"]),
            title=str(row["title"]),
            content=str(row["content"]),
            domain=str(row["domain"]),
            source=str(row["source"]),
            version=str(row["version"]),
            tags=list(row.get("tags") or []),
            part_codes=list(row.get("part_codes") or []),
            supplier_codes=list(row.get("supplier_codes") or []),
        )

    @staticmethod
    def _vector_literal(vector: list[float]) -> str:
        return "[" + ",".join(f"{float(value):.10g}" for value in vector) + "]"

    def upsert(self, doc: KnowledgeDoc) -> None:
        # Runtime import avoids a module cycle: embeddings uses store.tokenize.
        from .embeddings import encode_text

        embedding, backend = encode_text(f"{doc.title}\n{doc.content}")
        vector = self._vector_literal(embedding) if embedding else None
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO knowledge.documents(
                    id, title, content, domain, source, version, tags,
                    part_codes, supplier_codes, embedding, embedding_backend
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s)
                ON CONFLICT (id) DO UPDATE SET
                    title = EXCLUDED.title,
                    content = EXCLUDED.content,
                    domain = EXCLUDED.domain,
                    source = EXCLUDED.source,
                    version = EXCLUDED.version,
                    tags = EXCLUDED.tags,
                    part_codes = EXCLUDED.part_codes,
                    supplier_codes = EXCLUDED.supplier_codes,
                    embedding = EXCLUDED.embedding,
                    embedding_backend = EXCLUDED.embedding_backend,
                    updated_at = now()
                """,
                (
                    doc.id,
                    doc.title,
                    doc.content,
                    doc.domain,
                    doc.source,
                    doc.version,
                    Jsonb(doc.tags),
                    Jsonb(doc.part_codes),
                    Jsonb(doc.supplier_codes),
                    vector,
                    backend,
                ),
            )

    def get(self, doc_id: str) -> Optional[KnowledgeDoc]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM knowledge.documents WHERE id = %s", (doc_id,))
            row = cur.fetchone()
            return self._row_to_doc(row) if row else None

    def all(self) -> list[KnowledgeDoc]:
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM knowledge.documents ORDER BY id")
            return [self._row_to_doc(row) for row in cur.fetchall()]

    def filter(
        self,
        *,
        domain: Optional[str] = None,
        part_code: Optional[str] = None,
        supplier_code: Optional[str] = None,
    ) -> list[KnowledgeDoc]:
        clauses: list[str] = []
        params: list[Any] = []
        if domain:
            clauses.append("domain = %s")
            params.append(domain)
        if part_code:
            clauses.append("(part_codes @> %s OR upper(content) LIKE %s)")
            params.extend([Jsonb([part_code]), f"%{part_code.upper()}%"])
        if supplier_code:
            clauses.append("(supplier_codes @> %s OR upper(content) LIKE %s)")
            params.extend([Jsonb([supplier_code]), f"%{supplier_code.upper()}%"])
        sql = "SELECT * FROM knowledge.documents"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY id"
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            return [self._row_to_doc(row) for row in cur.fetchall()]

    def load_json(self, path: Path) -> int:
        rows = json.loads(path.read_text(encoding="utf-8"))
        for row in rows:
            self.upsert(KnowledgeDoc(**row))
        return len(rows)

    def vector_search(
        self,
        query_vector: list[float],
        *,
        domain: Optional[str] = None,
        top_k: int = 12,
    ) -> list[tuple[KnowledgeDoc, float, str]]:
        if not query_vector:
            return []
        vector = self._vector_literal(query_vector)
        params: list[Any] = [vector, len(query_vector)]
        domain_sql = ""
        if domain:
            domain_sql = " AND domain = %s"
            params.append(domain)
        params.append(max(1, min(int(top_k), 100)))
        with self.pool.connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT *, 1 - (embedding <=> %s::vector) AS vector_score
                FROM knowledge.documents
                WHERE embedding IS NOT NULL
                  AND vector_dims(embedding) = %s
                  {domain_sql}
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                tuple([*params[:-1], vector, params[-1]]),
            )
            return [
                (
                    self._row_to_doc(row),
                    float(row["vector_score"] or 0.0),
                    str(row.get("embedding_backend") or "pgvector"),
                )
                for row in cur.fetchall()
            ]


_DEFAULT: Optional[KnowledgeStore] = None
_DEFAULT_MTIME: Optional[float] = None


def get_default_store() -> KnowledgeStore:
    global _DEFAULT, _DEFAULT_MTIME
    mtime = SEED_PATH.stat().st_mtime if SEED_PATH.exists() else None
    if _DEFAULT is None or (_DEFAULT_MTIME is not None and mtime != _DEFAULT_MTIME):
        store = PostgresKnowledgeStore()
        if SEED_PATH.exists():
            store.load_json(SEED_PATH)
        _DEFAULT = store
        _DEFAULT_MTIME = mtime
    return _DEFAULT


def tokenize(text: str) -> list[str]:
    text = (text or "").lower()
    # 中英混切：连续汉字 / 字母数字
    parts = re.findall(r"[\u4e00-\u9fff]{1,}|[a-z0-9][\w\-]*", text)
    tokens: list[str] = []
    for p in parts:
        if re.fullmatch(r"[\u4e00-\u9fff]+", p) and len(p) > 2:
            tokens.extend(p[i : i + 2] for i in range(len(p) - 1))
        tokens.append(p)
    return tokens
