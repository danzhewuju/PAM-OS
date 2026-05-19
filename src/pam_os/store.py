from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from pam_os.models import ContextPackage, Event, Memory, SearchResult


class MemoryStore:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._fts_available: bool | None = None
        self.init()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                  id TEXT PRIMARY KEY,
                  source TEXT NOT NULL,
                  source_ref TEXT,
                  content TEXT NOT NULL,
                  metadata_json TEXT NOT NULL DEFAULT '{}',
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS memories (
                  id TEXT PRIMARY KEY,
                  event_id TEXT NOT NULL,
                  type TEXT NOT NULL,
                  content TEXT NOT NULL,
                  importance REAL NOT NULL,
                  confidence REAL NOT NULL,
                  tags_json TEXT NOT NULL DEFAULT '[]',
                  valid_from TEXT,
                  valid_to TEXT,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  FOREIGN KEY(event_id) REFERENCES events(id)
                );

                CREATE TABLE IF NOT EXISTS memory_links (
                  id TEXT PRIMARY KEY,
                  source_memory_id TEXT NOT NULL,
                  target_memory_id TEXT NOT NULL,
                  relation TEXT NOT NULL,
                  weight REAL NOT NULL DEFAULT 1.0,
                  created_at TEXT NOT NULL,
                  FOREIGN KEY(source_memory_id) REFERENCES memories(id),
                  FOREIGN KEY(target_memory_id) REFERENCES memories(id)
                );

                CREATE TABLE IF NOT EXISTS context_packages (
                  id TEXT PRIMARY KEY,
                  task TEXT NOT NULL,
                  content TEXT NOT NULL,
                  memory_ids_json TEXT NOT NULL DEFAULT '[]',
                  created_at TEXT NOT NULL
                );
                """
            )
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                    USING fts5(id UNINDEXED, content, tags)
                    """
                )
                self._fts_available = True
            except sqlite3.OperationalError:
                self._fts_available = False

    def add_event(self, event: Event) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO events(id, source, source_ref, content, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.source,
                    event.source_ref,
                    event.content,
                    json.dumps(event.metadata, ensure_ascii=False),
                    event.created_at,
                ),
            )

    def add_memories(self, memories: list[Memory]) -> None:
        with self.connect() as conn:
            for memory in memories:
                conn.execute(
                    """
                    INSERT INTO memories(
                      id, event_id, type, content, importance, confidence, tags_json,
                      valid_from, valid_to, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        memory.id,
                        memory.event_id,
                        memory.type,
                        memory.content,
                        memory.importance,
                        memory.confidence,
                        json.dumps(memory.tags, ensure_ascii=False),
                        memory.valid_from,
                        memory.valid_to,
                        memory.created_at,
                        memory.updated_at,
                    ),
                )
                if self.fts_available:
                    conn.execute(
                        "INSERT INTO memories_fts(id, content, tags) VALUES (?, ?, ?)",
                        (memory.id, memory.content, " ".join(memory.tags)),
                    )

    @property
    def fts_available(self) -> bool:
        if self._fts_available is not None:
            return self._fts_available
        with self.connect() as conn:
            try:
                conn.execute("SELECT count(*) FROM memories_fts").fetchone()
                self._fts_available = True
            except sqlite3.OperationalError:
                self._fts_available = False
        return self._fts_available

    def search_memories(
        self,
        query: str,
        *,
        limit: int = 10,
        types: list[str] | None = None,
        min_importance: float = 0.0,
        min_confidence: float = 0.0,
    ) -> list[SearchResult]:
        if self.fts_available:
            try:
                results = self._search_memories_fts(query, limit, types, min_importance, min_confidence)
                if results:
                    return results
            except sqlite3.OperationalError:
                self._fts_available = False
        return self._search_memories_like(query, limit, types, min_importance, min_confidence)

    def recent_memories(self, *, limit: int = 50) -> list[Memory]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_memory(row) for row in rows]

    def save_context_package(self, package: ContextPackage) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO context_packages(id, task, content, memory_ids_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    package.id,
                    package.task,
                    package.content,
                    json.dumps(package.memory_ids, ensure_ascii=False),
                    package.created_at,
                ),
            )

    def _search_memories_fts(
        self,
        query: str,
        limit: int,
        types: list[str] | None,
        min_importance: float,
        min_confidence: float,
    ) -> list[SearchResult]:
        fts_query = self._build_fts_query(query)
        if not fts_query:
            return []
        where = ["memories_fts MATCH ?", "m.importance >= ?", "m.confidence >= ?"]
        params: list[Any] = [fts_query, min_importance, min_confidence]
        if types:
            where.append(f"m.type IN ({','.join('?' for _ in types)})")
            params.extend(types)
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT m.*, bm25(memories_fts) AS rank
                FROM memories_fts
                JOIN memories m ON m.id = memories_fts.id
                WHERE {' AND '.join(where)}
                ORDER BY rank ASC, m.importance DESC, m.confidence DESC, m.updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            SearchResult(memory=self._row_to_memory(row), score=float(row["rank"] or 0.0))
            for row in rows
        ]

    def _search_memories_like(
        self,
        query: str,
        limit: int,
        types: list[str] | None,
        min_importance: float,
        min_confidence: float,
    ) -> list[SearchResult]:
        terms = self._terms(query)
        where = ["m.importance >= ?", "m.confidence >= ?"]
        params: list[Any] = [min_importance, min_confidence]
        if terms:
            like_parts = []
            for term in terms:
                like_parts.append("(m.content LIKE ? OR m.tags_json LIKE ?)")
                params.extend([f"%{term}%", f"%{term}%"])
            where.append("(" + " OR ".join(like_parts) + ")")
        if types:
            where.append(f"m.type IN ({','.join('?' for _ in types)})")
            params.extend(types)
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT m.*
                FROM memories m
                WHERE {' AND '.join(where)}
                ORDER BY m.importance DESC, m.confidence DESC, m.updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [
            SearchResult(
                memory=self._row_to_memory(row),
                score=self._like_score(row["content"], row["tags_json"], terms),
            )
            for row in rows
        ]

    def _build_fts_query(self, query: str) -> str:
        terms = self._terms(query)
        if not terms:
            return ""
        return " OR ".join(f'"{term}"' for term in terms)

    def _terms(self, query: str) -> list[str]:
        tokens = [token.strip() for token in query.replace("，", " ").replace("？", " ").split()]
        ascii_tokens = []
        for token in re_split_words(query):
            if token not in tokens:
                ascii_tokens.append(token)
        cjk_keywords = [
            keyword
            for keyword in [
                "偏好",
                "项目",
                "目标",
                "风格",
                "记忆",
                "实现",
                "方案",
                "本地",
                "可控",
                "技术",
                "工程",
                "下一步",
                "长期",
                "思源",
            ]
            if keyword in query
        ]
        result = tokens + ascii_tokens + cjk_keywords
        return [term for index, term in enumerate(result) if term and term not in result[:index]][:12]

    def _like_score(self, content: str, tags_json: str, terms: list[str]) -> float:
        haystack = f"{content} {tags_json}".lower()
        if not terms:
            return 0.0
        hits = sum(1 for term in terms if term.lower() in haystack)
        return hits / len(terms)

    def _row_to_memory(self, row: sqlite3.Row) -> Memory:
        return Memory(
            id=row["id"],
            event_id=row["event_id"],
            type=row["type"],
            content=row["content"],
            importance=float(row["importance"]),
            confidence=float(row["confidence"]),
            tags=json.loads(row["tags_json"] or "[]"),
            valid_from=row["valid_from"],
            valid_to=row["valid_to"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


def re_split_words(query: str) -> list[str]:
    import re

    return re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}", query)
