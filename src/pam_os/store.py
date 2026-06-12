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
    PolicySignal,
    ProfileEvidence,
    QualityTrace,
    ProfileTrait,
    SearchResult,
    StorageStats,
    now_iso,
)


INSPECT_TABLES = {
    "events": {
        "order_by": "created_at DESC",
        "json_columns": {"metadata_json": "metadata"},
        "text_columns": ["id", "source", "source_ref", "content"],
    },
    "memories": {
        "order_by": "created_at DESC",
        "json_columns": {"tags_json": "tags"},
        "text_columns": ["id", "event_id", "type", "content", "tags_json"],
    },
    "profile_evidence": {
        "order_by": "created_at DESC",
        "json_columns": {},
        "text_columns": ["id", "trait_key", "evidence_type", "content", "source_event_id", "source_memory_id"],
    },
    "profile_traits": {
        "order_by": "updated_at DESC",
        "json_columns": {"evidence_ids_json": "evidence_ids"},
        "text_columns": ["id", "trait_type", "trait_key", "statement", "scope", "status"],
    },
    "behavior_events": {
        "order_by": "created_at DESC",
        "json_columns": {
            "chosen_json": "chosen",
            "rejected_json": "rejected",
            "deferred_json": "deferred",
        },
        "text_columns": ["id", "context", "chosen_json", "rejected_json", "deferred_json", "reason", "source_ref"],
    },
    "context_packages": {
        "order_by": "created_at DESC",
        "json_columns": {"memory_ids_json": "memory_ids"},
        "text_columns": ["id", "task", "content", "memory_ids_json"],
    },
    "memory_links": {
        "order_by": "created_at DESC",
        "json_columns": {},
        "text_columns": ["id", "source_memory_id", "target_memory_id", "relation"],
    },
    "policy_signals": {
        "order_by": "updated_at DESC",
        "json_columns": {},
        "text_columns": ["id", "signal_type", "scope", "pattern", "normalized_intent", "action", "source", "status"],
    },
    "quality_traces": {
        "order_by": "created_at DESC",
        "json_columns": {
            "signals_json": "signals",
            "related_ids_json": "related_ids",
            "metrics_json": "metrics",
        },
        "text_columns": ["id", "trace_id", "operation", "stage", "input_summary", "provider", "decision", "error"],
    },
}


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

                CREATE TABLE IF NOT EXISTS policy_signals (
                  id TEXT PRIMARY KEY,
                  signal_type TEXT NOT NULL,
                  scope TEXT NOT NULL,
                  pattern TEXT NOT NULL,
                  normalized_intent TEXT NOT NULL,
                  action TEXT NOT NULL,
                  confidence REAL NOT NULL,
                  support_count INTEGER NOT NULL,
                  reject_count INTEGER NOT NULL,
                  source TEXT NOT NULL,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE(signal_type, pattern, action)
                );

                CREATE TABLE IF NOT EXISTS quality_traces (
                  id TEXT PRIMARY KEY,
                  trace_id TEXT NOT NULL,
                  operation TEXT NOT NULL,
                  stage TEXT NOT NULL,
                  input_summary TEXT NOT NULL,
                  provider TEXT NOT NULL,
                  decision TEXT NOT NULL,
                  confidence REAL,
                  signals_json TEXT NOT NULL DEFAULT '[]',
                  related_ids_json TEXT NOT NULL DEFAULT '[]',
                  metrics_json TEXT NOT NULL DEFAULT '{}',
                  error TEXT,
                  created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_quality_traces_trace_id
                ON quality_traces(trace_id, created_at);
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
                self._insert_memory(conn, memory)

    def upsert_deduped_memories(
        self,
        memories: list[Memory],
        *,
        similarity_threshold: float = 0.82,
    ) -> tuple[list[Memory], int, int]:
        if not memories:
            return [], 0, 0

        resolved: list[Memory] = []
        created_count = 0
        updated_count = 0
        with self.connect() as conn:
            for memory in memories:
                existing = self._find_similar_memory(conn, memory, similarity_threshold=similarity_threshold)
                if existing:
                    updated = self._reinforce_memory(conn, existing, memory)
                    resolved.append(updated)
                    updated_count += 1
                    continue

                self._insert_memory(conn, memory)
                resolved.append(memory)
                created_count += 1
        return resolved, created_count, updated_count

    def _insert_memory(self, conn: sqlite3.Connection, memory: Memory) -> None:
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

    def _find_similar_memory(
        self,
        conn: sqlite3.Connection,
        memory: Memory,
        *,
        similarity_threshold: float,
    ) -> Memory | None:
        rows = conn.execute(
            """
            SELECT *
            FROM memories
            WHERE type = ?
            ORDER BY updated_at DESC
            LIMIT 200
            """,
            (memory.type,),
        ).fetchall()
        best: tuple[float, Memory] | None = None
        candidate_terms = _content_terms(memory.content)
        for row in rows:
            existing = self._row_to_memory(row)
            existing_terms = _content_terms(existing.content)
            score = _memory_similarity(candidate_terms, existing_terms)
            if score >= similarity_threshold and (best is None or score > best[0]):
                best = (score, existing)
        return best[1] if best else None

    def _reinforce_memory(self, conn: sqlite3.Connection, existing: Memory, candidate: Memory) -> Memory:
        timestamp = now_iso()
        tags = sorted({*existing.tags, *candidate.tags})
        updated = Memory(
            id=existing.id,
            event_id=existing.event_id,
            type=existing.type,
            content=_prefer_more_specific(existing.content, candidate.content),
            importance=min(0.98, max(existing.importance, candidate.importance) + 0.02),
            confidence=min(0.98, max(existing.confidence, candidate.confidence) + 0.03),
            tags=tags,
            valid_from=existing.valid_from,
            valid_to=existing.valid_to,
            created_at=existing.created_at,
            updated_at=timestamp,
        )
        conn.execute(
            """
            UPDATE memories
            SET content = ?, importance = ?, confidence = ?, tags_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                updated.content,
                updated.importance,
                updated.confidence,
                json.dumps(updated.tags, ensure_ascii=False),
                updated.updated_at,
                updated.id,
            ),
        )
        if self.fts_available:
            conn.execute("DELETE FROM memories_fts WHERE id = ?", (updated.id,))
            conn.execute(
                "INSERT INTO memories_fts(id, content, tags) VALUES (?, ?, ?)",
                (updated.id, updated.content, " ".join(updated.tags)),
            )
        return updated

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
        fts_results: list[SearchResult] = []
        if self.fts_available:
            try:
                fts_results = self._search_memories_fts(query, limit, types, min_importance, min_confidence)
            except sqlite3.OperationalError:
                self._fts_available = False
        like_results = self._search_memories_like(query, limit, types, min_importance, min_confidence)
        return _merge_search_results(fts_results, like_results, limit=limit)

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
                "events": {
                    "count": self._count_rows(conn, "events"),
                    "by_source": self._grouped_counts(conn, "events", "source"),
                    **self._event_capture_diagnostics(conn),
                },
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
                "policy_signals": {
                    "count": self._count_rows(conn, "policy_signals"),
                    "by_status": self._grouped_counts(conn, "policy_signals", "status"),
                },
                "quality_traces": {"count": self._count_rows(conn, "quality_traces")},
            }
            latest_write_at = self._latest_write_at(conn)

        return StorageStats(
            db_path=str(self.db_path),
            db_size_bytes=db_size_bytes,
            fts_available=self.fts_available,
            latest_write_at=latest_write_at,
            tables=tables,
        )

    def inspect_memory(self, *, table: str = "all", limit: int = 20, query: str | None = None) -> dict[str, Any]:
        if table != "all" and table not in INSPECT_TABLES:
            allowed = ", ".join(["all", *INSPECT_TABLES])
            raise ValueError(f"table must be one of: {allowed}")

        db_size_bytes = 0
        try:
            db_size_bytes = self.db_path.stat().st_size
        except FileNotFoundError:
            pass

        with self.connect() as conn:
            existing_tables = self._list_tables(conn)
            table_names = list(INSPECT_TABLES) if table == "all" else [table]
            table_names = [name for name in table_names if name in existing_tables]
            stats = {
                "db_path": str(self.db_path),
                "db_size_bytes": db_size_bytes,
                "fts_available": "memories_fts" in existing_tables,
                "latest_write_at": self._latest_write_at_for_tables(conn, existing_tables),
                "tables": self._inspect_table_counts(conn, existing_tables),
            }
            details = {
                name: self._fetch_inspect_rows(conn, table=name, limit=limit, query=query)
                for name in table_names
            }
        return {"stats": stats, "details": details}

    def add_quality_trace(self, trace: QualityTrace) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO quality_traces(
                  id, trace_id, operation, stage, input_summary, provider, decision,
                  confidence, signals_json, related_ids_json, metrics_json, error, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace.id,
                    trace.trace_id,
                    trace.operation,
                    trace.stage,
                    trace.input_summary,
                    trace.provider,
                    trace.decision,
                    trace.confidence,
                    json.dumps(trace.signals, ensure_ascii=False),
                    json.dumps(trace.related_ids, ensure_ascii=False),
                    json.dumps(trace.metrics, ensure_ascii=False),
                    trace.error,
                    trace.created_at,
                ),
            )

    def mark_behavior_events_consolidated(self, ids: list[str], timestamp: str) -> None:
        if not ids:
            return
        with self.connect() as conn:
            conn.executemany(
                "UPDATE behavior_events SET consolidated_at = ? WHERE id = ?",
                [(timestamp, event_id) for event_id in ids],
            )

    def clear_all(self) -> dict[str, int]:
        tables = [
            "memory_links",
            "context_packages",
            "profile_evidence",
            "profile_traits",
            "quality_traces",
            "behavior_events",
            "policy_signals",
            "memories",
            "events",
        ]
        with self.connect() as conn:
            deleted_counts = {table: self._count_rows(conn, table) for table in tables}
            for table in tables:
                conn.execute(f"DELETE FROM {table}")
            if self.fts_available:
                deleted_counts["memories_fts"] = self._count_fts_rows(conn)
                conn.execute("DELETE FROM memories_fts")
        return deleted_counts

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

    def upsert_policy_signal(self, signal: PolicySignal) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO policy_signals(
                  id, signal_type, scope, pattern, normalized_intent, action,
                  confidence, support_count, reject_count, source, status,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(signal_type, pattern, action) DO UPDATE SET
                  scope = excluded.scope,
                  normalized_intent = excluded.normalized_intent,
                  confidence = excluded.confidence,
                  support_count = excluded.support_count,
                  reject_count = excluded.reject_count,
                  source = excluded.source,
                  status = excluded.status,
                  updated_at = excluded.updated_at
                """,
                (
                    signal.id,
                    signal.signal_type,
                    signal.scope,
                    signal.pattern,
                    signal.normalized_intent,
                    signal.action,
                    signal.confidence,
                    signal.support_count,
                    signal.reject_count,
                    signal.source,
                    signal.status,
                    signal.created_at,
                    signal.updated_at,
                ),
            )

    def get_policy_signal(self, signal_type: str, pattern: str, action: str) -> PolicySignal | None:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM policy_signals
                WHERE signal_type = ? AND pattern = ? AND action = ?
                """,
                (signal_type, pattern, action),
            ).fetchone()
        return self._row_to_policy_signal(row) if row else None

    def list_policy_signals(
        self,
        *,
        signal_type: str | None = None,
        action: str | None = None,
        statuses: list[str] | None = None,
        limit: int = 50,
    ) -> list[PolicySignal]:
        where = []
        params: list[Any] = []
        if signal_type:
            where.append("signal_type = ?")
            params.append(signal_type)
        if action:
            where.append("action = ?")
            params.append(action)
        if statuses:
            where.append(f"status IN ({','.join('?' for _ in statuses)})")
            params.extend(statuses)
        params.append(limit)
        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT *
                FROM policy_signals
                {where_sql}
                ORDER BY status ASC, confidence DESC, support_count DESC, updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [self._row_to_policy_signal(row) for row in rows]

    def reinforce_policy_signal(
        self,
        *,
        signal_type: str,
        pattern: str,
        action: str,
        supported: bool,
        confidence_delta: float = 0.08,
    ) -> PolicySignal | None:
        signal = self.get_policy_signal(signal_type, pattern, action)
        if not signal:
            return None
        support_count = signal.support_count + (1 if supported else 0)
        reject_count = signal.reject_count + (0 if supported else 1)
        confidence = signal.confidence + confidence_delta if supported else signal.confidence - confidence_delta
        confidence = max(0.0, min(0.98, confidence))
        status = _policy_signal_status(confidence, support_count, reject_count)
        updated = PolicySignal(
            id=signal.id,
            signal_type=signal.signal_type,
            scope=signal.scope,
            pattern=signal.pattern,
            normalized_intent=signal.normalized_intent,
            action=signal.action,
            confidence=confidence,
            support_count=support_count,
            reject_count=reject_count,
            source=signal.source,
            status=status,
            created_at=signal.created_at,
            updated_at=now_iso(),
        )
        self.upsert_policy_signal(updated)
        return updated

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
        identity_terms = _identity_query_terms(query)
        result = tokens + ascii_tokens + cjk_keywords + identity_terms
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

    def _row_to_policy_signal(self, row: sqlite3.Row) -> PolicySignal:
        return PolicySignal(
            id=row["id"],
            signal_type=row["signal_type"],
            scope=row["scope"],
            pattern=row["pattern"],
            normalized_intent=row["normalized_intent"],
            action=row["action"],
            confidence=float(row["confidence"]),
            support_count=int(row["support_count"]),
            reject_count=int(row["reject_count"]),
            source=row["source"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _list_tables(self, conn: sqlite3.Connection) -> set[str]:
        rows = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type IN ('table', 'virtual table')
            """
        ).fetchall()
        return {row["name"] for row in rows}

    def _inspect_table_counts(self, conn: sqlite3.Connection, existing_tables: set[str]) -> dict[str, Any]:
        counts: dict[str, Any] = {}
        for table in INSPECT_TABLES:
            if table not in existing_tables:
                counts[table] = {"exists": False, "count": 0}
                continue
            counts[table] = {"exists": True, "count": self._count_rows(conn, table)}

        if "events" in existing_tables:
            counts["events"]["by_source"] = self._grouped_counts(conn, "events", "source")
            counts["events"].update(self._event_capture_diagnostics(conn))

        if "memories" in existing_tables:
            counts["memories"]["by_type"] = self._grouped_counts(conn, "memories", "type")
            counts["memories"]["unconsolidated_count"] = self._count_unconsolidated_memories(conn)

        if "profile_traits" in existing_tables:
            counts["profile_traits"]["by_status"] = self._grouped_counts(conn, "profile_traits", "status")

        if "behavior_events" in existing_tables:
            counts["behavior_events"]["unconsolidated_count"] = self._count_unconsolidated_behavior_events(conn)

        if "policy_signals" in existing_tables:
            counts["policy_signals"]["by_status"] = self._grouped_counts(conn, "policy_signals", "status")

        return counts

    def _event_capture_diagnostics(self, conn: sqlite3.Connection) -> dict[str, Any]:
        diagnostics = {
            "manual_capture_count": 0,
            "manual_override_count": 0,
            "policy_skip_manual_capture_count": 0,
            "by_capture_reason": {},
            "by_capture_policy_decision": {},
        }
        try:
            rows = conn.execute("SELECT metadata_json FROM events").fetchall()
        except sqlite3.OperationalError:
            return diagnostics
        reason_counts: dict[str, int] = {}
        policy_counts: dict[str, int] = {}
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except json.JSONDecodeError:
                metadata = {}
            trigger = str(metadata.get("trigger", "")).strip().lower()
            source = str(metadata.get("source", "")).strip().lower()
            manual_capture = trigger == "pamw" or source == "codex_pamw" or metadata.get("explicit_memory") is True
            if manual_capture:
                diagnostics["manual_capture_count"] += 1
            if metadata.get("manual_override") is True:
                diagnostics["manual_override_count"] += 1
            policy_decision = str(metadata.get("capture_policy_decision", "")).strip()
            if policy_decision:
                policy_counts[policy_decision] = policy_counts.get(policy_decision, 0) + 1
            if manual_capture and policy_decision == "skip_capture":
                diagnostics["policy_skip_manual_capture_count"] += 1
            reason = str(metadata.get("capture_reason", "")).strip()
            if reason:
                reason_counts[reason] = reason_counts.get(reason, 0) + 1
        diagnostics["by_capture_reason"] = reason_counts
        diagnostics["by_capture_policy_decision"] = policy_counts
        return diagnostics

    def _fetch_inspect_rows(
        self,
        conn: sqlite3.Connection,
        *,
        table: str,
        limit: int,
        query: str | None,
    ) -> list[dict[str, Any]]:
        config = INSPECT_TABLES[table]
        columns = self._table_columns(conn, table)
        where = ""
        params: list[Any] = []
        if query:
            text_columns = [column for column in config["text_columns"] if column in columns]
            if text_columns:
                where = "WHERE " + " OR ".join(f"{column} LIKE ?" for column in text_columns)
                params.extend([f"%{query}%"] * len(text_columns))
        params.append(max(limit, 0))
        rows = conn.execute(
            f"""
            SELECT *
            FROM {table}
            {where}
            ORDER BY {config["order_by"]}
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [self._normalize_inspect_row(row, config["json_columns"]) for row in rows]

    def _table_columns(self, conn: sqlite3.Connection, table: str) -> set[str]:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        return {row["name"] for row in rows}

    def _normalize_inspect_row(self, row: sqlite3.Row, json_columns: dict[str, str]) -> dict[str, Any]:
        item = dict(row)
        for source, target in json_columns.items():
            if source not in item:
                continue
            item[target] = self._parse_json_value(item.pop(source))
        return item

    def _parse_json_value(self, value: Any) -> Any:
        if value in (None, ""):
            return None
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return value

    def _count_rows(self, conn: sqlite3.Connection, table: str) -> int:
        row = conn.execute(f"SELECT count(*) AS count FROM {table}").fetchone()
        return int(row["count"] if row else 0)

    def _count_fts_rows(self, conn: sqlite3.Connection) -> int:
        try:
            row = conn.execute("SELECT count(*) AS count FROM memories_fts").fetchone()
        except sqlite3.OperationalError:
            return 0
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
                UNION ALL
                SELECT updated_at AS ts FROM policy_signals
                UNION ALL
                SELECT created_at AS ts FROM quality_traces
            )
            """
        ).fetchone()
        return row["latest_write_at"] if row and row["latest_write_at"] else None

    def _latest_write_at_for_tables(self, conn: sqlite3.Connection, existing_tables: set[str]) -> str | None:
        candidates = [
            ("events", "created_at"),
            ("memories", "updated_at"),
            ("memory_links", "created_at"),
            ("context_packages", "created_at"),
            ("profile_evidence", "created_at"),
            ("profile_traits", "updated_at"),
            ("behavior_events", "created_at"),
            ("policy_signals", "updated_at"),
            ("quality_traces", "created_at"),
        ]
        selects = [
            f"SELECT {column} AS ts FROM {table}"
            for table, column in candidates
            if table in existing_tables
        ]
        if not selects:
            return None
        row = conn.execute(f"SELECT MAX(ts) AS latest_write_at FROM ({' UNION ALL '.join(selects)})").fetchone()
        return row["latest_write_at"] if row and row["latest_write_at"] else None


def _merge_search_results(
    fts_results: list[SearchResult],
    like_results: list[SearchResult],
    *,
    limit: int,
) -> list[SearchResult]:
    by_id: dict[str, SearchResult] = {}
    for result in [*fts_results, *like_results]:
        existing = by_id.get(result.memory.id)
        if existing is None or _search_sort_score(result) > _search_sort_score(existing):
            by_id[result.memory.id] = result

    return sorted(
        by_id.values(),
        key=lambda result: (
            _search_sort_score(result),
            result.memory.importance,
            result.memory.confidence,
            result.memory.updated_at,
        ),
        reverse=True,
    )[:limit]


def _search_sort_score(result: SearchResult) -> float:
    if result.score < 0:
        return min(1.0, abs(result.score) * 100000)
    return max(0.0, min(1.0, result.score))


def re_split_words(query: str) -> list[str]:
    import re

    return re.findall(r"[A-Za-z][A-Za-z0-9_-]{1,}", query)


def _identity_query_terms(query: str) -> list[str]:
    normalized = query.lower()
    cjk_markers = [
        "我是谁",
        "你知道我是谁",
        "我的名字",
        "我叫什么",
        "我叫啥",
        "姓名",
        "名字",
        "身份",
    ]
    english_markers = [
        "who am i",
        "who i am",
        "my name",
        "what am i called",
        "what is my name",
        "identity",
    ]
    if not any(marker in query for marker in cjk_markers) and not any(marker in normalized for marker in english_markers):
        return []
    return ["用户叫", "用户姓名", "用户身份", "姓名", "名字", "identity"]


def _content_terms(content: str) -> set[str]:
    normalized = (
        content.lower()
        .replace("，", " ")
        .replace("。", " ")
        .replace("、", " ")
        .replace("：", " ")
        .replace("；", " ")
        .replace("/", " ")
    )
    terms = {
        token
        for token in normalized.split()
        if len(token) >= 2 and token not in {"用户", "偏好", "倾向", "上下文", "目标", "计划"}
    }
    terms.update(re_split_words(normalized))
    for keyword in [
        "自动",
        "触发",
        "写入",
        "记忆",
        "偏好",
        "项目",
        "决策",
        "风格",
        "确认",
        "重复",
        "合并",
        "本地",
        "可控",
        "轻量",
        "工程",
    ]:
        if keyword in content:
            terms.add(keyword)
    return terms or {normalized.strip()}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _memory_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    jaccard = _jaccard(left, right)
    containment = len(left & right) / min(len(left), len(right))
    if containment >= 0.8 and jaccard >= 0.45:
        return containment
    return jaccard


def _prefer_more_specific(existing: str, candidate: str) -> str:
    if existing == candidate:
        return existing
    if len(candidate) > len(existing) + 8 and _memory_similarity(_content_terms(existing), _content_terms(candidate)) >= 0.8:
        return candidate
    return existing


def _policy_signal_status(confidence: float, support_count: int, reject_count: int) -> str:
    if reject_count >= max(2, support_count):
        return "archived"
    if confidence >= 0.85 and support_count >= 3:
        return "stable"
    if confidence >= 0.62 and support_count >= 1:
        return "active"
    return "candidate"
