from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_DB = Path(".pam-os") / "memory.sqlite3"
TABLES = {
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
}


def main() -> int:
    args = parse_args()
    db_path = args.db.resolve()
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return 2

    with connect(db_path) as conn:
        report = build_report(
            conn,
            db_path=db_path,
            selected=args.table,
            limit=args.limit,
            query=args.query,
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_text_report(report)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect PAM-OS memory SQLite details.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"SQLite database path. Default: {DEFAULT_DB}")
    parser.add_argument("--limit", type=int, default=20, help="Maximum rows per table. Default: 20")
    parser.add_argument("--query", help="Case-insensitive keyword filter for detail rows.")
    parser.add_argument(
        "--table",
        choices=["all", *TABLES.keys()],
        default="all",
        help="Detail table to show. Default: all",
    )
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    return parser.parse_args()


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def build_report(
    conn: sqlite3.Connection,
    *,
    db_path: Path,
    selected: str,
    limit: int,
    query: str | None,
) -> dict[str, Any]:
    existing_tables = list_tables(conn)
    table_names = list(TABLES) if selected == "all" else [selected]
    table_names = [table for table in table_names if table in existing_tables]

    stats = {
        "db_path": str(db_path),
        "db_size_bytes": db_path.stat().st_size,
        "fts_available": "memories_fts" in existing_tables,
        "latest_write_at": latest_write_at(conn, existing_tables),
        "tables": table_counts(conn, existing_tables),
    }

    details = {
        table: fetch_rows(conn, table=table, limit=limit, query=query)
        for table in table_names
    }
    return {"stats": stats, "details": details}


def list_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type IN ('table', 'virtual table')
        """
    ).fetchall()
    return {row["name"] for row in rows}


def table_counts(conn: sqlite3.Connection, existing_tables: set[str]) -> dict[str, Any]:
    counts: dict[str, Any] = {}
    for table in TABLES:
        if table not in existing_tables:
            counts[table] = {"exists": False, "count": 0}
            continue
        counts[table] = {"exists": True, "count": scalar_int(conn, f"SELECT count(*) FROM {table}")}

    if "memories" in existing_tables:
        counts["memories"]["by_type"] = grouped_counts(conn, "memories", "type")
        counts["memories"]["unconsolidated_count"] = scalar_int(
            conn,
            """
            SELECT count(*)
            FROM memories m
            WHERE NOT EXISTS (
              SELECT 1 FROM profile_evidence e WHERE e.source_memory_id = m.id
            )
            """,
        )

    if "profile_traits" in existing_tables:
        counts["profile_traits"]["by_status"] = grouped_counts(conn, "profile_traits", "status")

    if "behavior_events" in existing_tables:
        counts["behavior_events"]["unconsolidated_count"] = scalar_int(
            conn,
            "SELECT count(*) FROM behavior_events WHERE consolidated_at IS NULL",
        )

    return counts


def scalar_int(conn: sqlite3.Connection, sql: str) -> int:
    row = conn.execute(sql).fetchone()
    if row is None:
        return 0
    return int(row[0] or 0)


def grouped_counts(conn: sqlite3.Connection, table: str, column: str) -> dict[str, int]:
    rows = conn.execute(
        f"""
        SELECT {column} AS value, count(*) AS count
        FROM {table}
        GROUP BY {column}
        ORDER BY count DESC, value ASC
        """
    ).fetchall()
    return {str(row["value"]): int(row["count"]) for row in rows}


def latest_write_at(conn: sqlite3.Connection, existing_tables: set[str]) -> str | None:
    candidates = [
        ("events", "created_at"),
        ("memories", "updated_at"),
        ("memory_links", "created_at"),
        ("context_packages", "created_at"),
        ("profile_evidence", "created_at"),
        ("profile_traits", "updated_at"),
        ("behavior_events", "created_at"),
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


def fetch_rows(
    conn: sqlite3.Connection,
    *,
    table: str,
    limit: int,
    query: str | None,
) -> list[dict[str, Any]]:
    config = TABLES[table]
    columns = table_columns(conn, table)
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
    return [normalize_row(row, config["json_columns"]) for row in rows]


def table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


def normalize_row(row: sqlite3.Row, json_columns: dict[str, str]) -> dict[str, Any]:
    item = dict(row)
    for source, target in json_columns.items():
        if source not in item:
            continue
        item[target] = parse_json(item.pop(source))
    return item


def parse_json(value: Any) -> Any:
    if value in (None, ""):
        return None
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def print_text_report(report: dict[str, Any]) -> None:
    stats = report["stats"]
    print("PAM-OS Memory Inspect")
    print("=" * 60)
    print(f"DB: {stats['db_path']}")
    print(f"Size: {stats['db_size_bytes']} bytes")
    print(f"FTS available: {stats['fts_available']}")
    print(f"Latest write: {stats['latest_write_at'] or '-'}")
    print()

    print("Table Counts")
    print("-" * 60)
    for table, info in stats["tables"].items():
        exists = "ok" if info["exists"] else "missing"
        extras = []
        if "by_type" in info:
            extras.append(f"by_type={info['by_type']}")
        if "by_status" in info:
            extras.append(f"by_status={info['by_status']}")
        if "unconsolidated_count" in info:
            extras.append(f"unconsolidated={info['unconsolidated_count']}")
        suffix = f" ({'; '.join(extras)})" if extras else ""
        print(f"{table}: {info['count']} [{exists}]{suffix}")
    print()

    for table, rows in report["details"].items():
        print(f"{table}")
        print("-" * 60)
        if not rows:
            print("(no rows)")
            print()
            continue
        for index, row in enumerate(rows, start=1):
            print(f"[{index}] {format_title(table, row)}")
            for key, value in row.items():
                if key in {"content", "statement", "task", "context"}:
                    print(f"  {key}: {value}")
            print(f"  id: {row.get('id')}")
            print(f"  meta: {format_meta(table, row)}")
        print()


def format_title(table: str, row: dict[str, Any]) -> str:
    if table == "memories":
        return f"{row.get('type')} importance={row.get('importance')} confidence={row.get('confidence')}"
    if table == "profile_traits":
        return f"{row.get('trait_key')} status={row.get('status')}"
    if table == "profile_evidence":
        return f"{row.get('trait_key')} evidence={row.get('evidence_type')}"
    if table == "behavior_events":
        return f"{row.get('created_at')} consolidated={row.get('consolidated_at') or 'no'}"
    if table == "events":
        return f"{row.get('source')} {row.get('created_at')}"
    if table == "context_packages":
        return f"{row.get('created_at')} memories={len(row.get('memory_ids') or [])}"
    if table == "memory_links":
        return f"{row.get('relation')} weight={row.get('weight')}"
    return str(row.get("id"))


def format_meta(table: str, row: dict[str, Any]) -> str:
    if table == "memories":
        return json.dumps(
            {
                "event_id": row.get("event_id"),
                "tags": row.get("tags"),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            },
            ensure_ascii=False,
        )
    if table == "profile_traits":
        return json.dumps(
            {
                "type": row.get("trait_type"),
                "scope": row.get("scope"),
                "stability": row.get("stability"),
                "confidence": row.get("confidence"),
                "evidence_count": row.get("evidence_count"),
                "evidence_ids": row.get("evidence_ids"),
                "updated_at": row.get("updated_at"),
            },
            ensure_ascii=False,
        )
    if table == "profile_evidence":
        return json.dumps(
            {
                "confidence": row.get("confidence"),
                "source_event_id": row.get("source_event_id"),
                "source_memory_id": row.get("source_memory_id"),
                "behavior_event_id": row.get("behavior_event_id"),
                "created_at": row.get("created_at"),
            },
            ensure_ascii=False,
        )
    if table == "behavior_events":
        return json.dumps(
            {
                "chosen": row.get("chosen"),
                "rejected": row.get("rejected"),
                "deferred": row.get("deferred"),
                "reason": row.get("reason"),
            },
            ensure_ascii=False,
        )
    if table == "events":
        return json.dumps({"source_ref": row.get("source_ref"), "metadata": row.get("metadata")}, ensure_ascii=False)
    if table == "context_packages":
        return json.dumps({"memory_ids": row.get("memory_ids")}, ensure_ascii=False)
    return json.dumps(row, ensure_ascii=False)


if __name__ == "__main__":
    raise SystemExit(main())
