from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from pam_os.config import RetrievalConfig
from pam_os.models import (
    BehaviorEvent,
    ContextPackage,
    Event,
    Memory,
    ProfileEvidence,
    ProfileTrait,
    SearchResult,
    StorageStats,
)


class MemoryStore:
    def __init__(self, db_path: Path | str, *, retrieval_config: RetrievalConfig | None = None):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._fts_available: bool | None = None
        self.retrieval_config = retrieval_config or RetrievalConfig()
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

                CREATE TABLE IF NOT EXISTS profile_evidence (
                  id TEXT PRIMARY KEY,
                  trait_key TEXT NOT NULL,
                  evidence_type TEXT NOT NULL,
                  content TEXT NOT NULL,
                  source_event_id TEXT,
                  source_memory_id TEXT,
                  behavior_event_id TEXT,
                  confidence REAL NOT NULL,
                  created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS profile_traits (
                  id TEXT PRIMARY KEY,
                  trait_type TEXT NOT NULL,
                  trait_key TEXT NOT NULL UNIQUE,
                  statement TEXT NOT NULL,
                  scope TEXT NOT NULL,
                  stability REAL NOT NULL,
                  confidence REAL NOT NULL,
                  evidence_count INTEGER NOT NULL,
                  evidence_ids_json TEXT NOT NULL DEFAULT '[]',
                  status TEXT NOT NULL,
                  first_seen_at TEXT NOT NULL,
                  last_confirmed_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS behavior_events (
                  id TEXT PRIMARY KEY,
                  context TEXT NOT NULL,
                  chosen_json TEXT NOT NULL DEFAULT '[]',
                  rejected_json TEXT NOT NULL DEFAULT '[]',
                  deferred_json TEXT NOT NULL DEFAULT '[]',
                  reason TEXT,
                  source_ref TEXT,
                  created_at TEXT NOT NULL,
                  consolidated_at TEXT
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

    def recent_unconsolidated_memories(self, *, limit: int = 100) -> list[Memory]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT m.*
                FROM memories m
                WHERE NOT EXISTS (
                  SELECT 1 FROM profile_evidence e WHERE e.source_memory_id = m.id
                )
                ORDER BY m.created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_memory(row) for row in rows]

    def add_behavior_event(self, event: BehaviorEvent) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO behavior_events(
                  id, context, chosen_json, rejected_json, deferred_json, reason, source_ref, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.id,
                    event.context,
                    json.dumps(event.chosen, ensure_ascii=False),
                    json.dumps(event.rejected, ensure_ascii=False),
                    json.dumps(event.deferred, ensure_ascii=False),
                    event.reason,
                    event.source_ref,
                    event.created_at,
                ),
            )

    def recent_unconsolidated_behavior_events(self, *, limit: int = 100) -> list[BehaviorEvent]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM behavior_events
                WHERE consolidated_at IS NULL
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_behavior_event(row) for row in rows]

    def get_storage_stats(self) -> StorageStats:
        db_size_bytes = 0
        try:
            db_size_bytes = self.db_path.stat().st_size
        except FileNotFoundError:
            pass

        with self.connect() as conn:
            tables = {
                "events": {"count": self._count_rows(conn, "events")},
                "memories": {
                    "count": self._count_rows(conn, "memories"),
                    "by_type": self._grouped_counts(conn, "memories", "type"),
                    "unconsolidated_count": self._count_unconsolidated_memories(conn),
                },
                "memory_links": {"count": self._count_rows(conn, "memory_links")},
                "context_packages": {"count": self._count_rows(conn, "context_packages")},
                "profile_evidence": {"count": self._count_rows(conn, "profile_evidence")},
                "profile_traits": {
                    "count": self._count_rows(conn, "profile_traits"),
                    "by_status": self._grouped_counts(conn, "profile_traits", "status"),
                },
                "behavior_events": {
                    "count": self._count_rows(conn, "behavior_events"),
                    "unconsolidated_count": self._count_unconsolidated_behavior_events(conn),
                },
            }
            latest_write_at = self._latest_write_at(conn)

        return StorageStats(
            db_path=str(self.db_path),
            db_size_bytes=db_size_bytes,
            fts_available=self.fts_available,
            latest_write_at=latest_write_at,
            tables=tables,
        )

    def mark_behavior_events_consolidated(self, ids: list[str], timestamp: str) -> None:
        if not ids:
            return
        with self.connect() as conn:
            conn.executemany(
                "UPDATE behavior_events SET consolidated_at = ? WHERE id = ?",
                [(timestamp, event_id) for event_id in ids],
            )

    def add_profile_evidence(self, evidence: list[ProfileEvidence]) -> None:
        if not evidence:
            return
        with self.connect() as conn:
            for item in evidence:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO profile_evidence(
                      id, trait_key, evidence_type, content, source_event_id,
                      source_memory_id, behavior_event_id, confidence, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item.id,
                        item.trait_key,
                        item.evidence_type,
                        item.content,
                        item.source_event_id,
                        item.source_memory_id,
                        item.behavior_event_id,
                        item.confidence,
                        item.created_at,
                    ),
                )

    def get_profile_trait(self, trait_key: str) -> ProfileTrait | None:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM profile_traits WHERE trait_key = ?", (trait_key,)).fetchone()
        return self._row_to_profile_trait(row) if row else None

    def upsert_profile_trait(self, trait: ProfileTrait) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO profile_traits(
                  id, trait_type, trait_key, statement, scope, stability, confidence,
                  evidence_count, evidence_ids_json, status, first_seen_at,
                  last_confirmed_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(trait_key) DO UPDATE SET
                  trait_type = excluded.trait_type,
                  statement = excluded.statement,
                  scope = excluded.scope,
                  stability = excluded.stability,
                  confidence = excluded.confidence,
                  evidence_count = excluded.evidence_count,
                  evidence_ids_json = excluded.evidence_ids_json,
                  status = excluded.status,
                  last_confirmed_at = excluded.last_confirmed_at,
                  updated_at = excluded.updated_at
                """,
                (
                    trait.id,
                    trait.trait_type,
                    trait.trait_key,
                    trait.statement,
                    trait.scope,
                    trait.stability,
                    trait.confidence,
                    trait.evidence_count,
                    json.dumps(trait.evidence_ids, ensure_ascii=False),
                    trait.status,
                    trait.first_seen_at,
                    trait.last_confirmed_at,
                    trait.updated_at,
                ),
            )

    def list_profile_traits(
        self,
        *,
        limit: int = 20,
        status: str = "active",
        query: str | None = None,
    ) -> list[ProfileTrait]:
        where = ["status = ?"]
        params: list[Any] = [status]
        if query:
            terms = self._terms(query)
            if terms:
                like_parts = []
                for term in terms:
                    like_parts.append("(statement LIKE ? OR trait_key LIKE ? OR scope LIKE ?)")
                    params.extend([f"%{term}%", f"%{term}%", f"%{term}%"])
                where.append("(" + " OR ".join(like_parts) + ")")
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM profile_traits
                WHERE {' AND '.join(where)}
                ORDER BY stability DESC, confidence DESC, evidence_count DESC, updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_profile_trait(row) for row in rows]

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
        return [
            term for index, term in enumerate(result) if term and term not in result[:index]
        ][: self.retrieval_config.max_query_terms]

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

    def _row_to_profile_trait(self, row: sqlite3.Row) -> ProfileTrait:
        return ProfileTrait(
            id=row["id"],
            trait_type=row["trait_type"],
            trait_key=row["trait_key"],
            statement=row["statement"],
            scope=row["scope"],
            stability=float(row["stability"]),
            confidence=float(row["confidence"]),
            evidence_count=int(row["evidence_count"]),
            evidence_ids=json.loads(row["evidence_ids_json"] or "[]"),
            status=row["status"],
            first_seen_at=row["first_seen_at"],
            last_confirmed_at=row["last_confirmed_at"],
            updated_at=row["updated_at"],
        )

    def _row_to_behavior_event(self, row: sqlite3.Row) -> BehaviorEvent:
        return BehaviorEvent(
            id=row["id"],
            context=row["context"],
            chosen=json.loads(row["chosen_json"] or "[]"),
            rejected=json.loads(row["rejected_json"] or "[]"),
            deferred=json.loads(row["deferred_json"] or "[]"),
            reason=row["reason"],
            source_ref=row["source_ref"],
            created_at=row["created_at"],
        )

    def _count_rows(self, conn: sqlite3.Connection, table: str) -> int:
        row = conn.execute(f"SELECT count(*) AS count FROM {table}").fetchone()
        return int(row["count"] if row else 0)

    def _grouped_counts(self, conn: sqlite3.Connection, table: str, column: str) -> dict[str, int]:
        rows = conn.execute(
            f"""
            SELECT {column} AS value, count(*) AS count
            FROM {table}
            GROUP BY {column}
            ORDER BY count DESC, value ASC
            """
        ).fetchall()
        return {str(row["value"]): int(row["count"]) for row in rows}

    def _count_unconsolidated_memories(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            """
            SELECT count(*) AS count
            FROM memories m
            WHERE NOT EXISTS (
              SELECT 1 FROM profile_evidence e WHERE e.source_memory_id = m.id
            )
            """
        ).fetchone()
        return int(row["count"] if row else 0)

    def _count_unconsolidated_behavior_events(self, conn: sqlite3.Connection) -> int:
        row = conn.execute(
            """
            SELECT count(*) AS count
            FROM behavior_events
            WHERE consolidated_at IS NULL
            """
        ).fetchone()
        return int(row["count"] if row else 0)

    def _latest_write_at(self, conn: sqlite3.Connection) -> str | None:
        row = conn.execute(
            """
            SELECT MAX(ts) AS latest_write_at
            FROM (
                SELECT created_at AS ts FROM events
                UNION ALL
                SELECT updated_at AS ts FROM memories
                UNION ALL
                SELECT created_at AS ts FROM memory_links
                UNION ALL
                SELECT created_at AS ts FROM context_packages
                UNION ALL
                SELECT created_at AS ts FROM profile_evidence
                UNION ALL
                SELECT updated_at AS ts FROM profile_traits
                UNION ALL
                SELECT created_at AS ts FROM behavior_events
            )
            """
        ).fetchone()
        return row["latest_write_at"] if row and row["latest_write_at"] else None


def re_split_words(query: str) -> list[str]:
    import re

    return re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}", query)
