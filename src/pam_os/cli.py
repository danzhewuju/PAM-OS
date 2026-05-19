from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from pam_os.config import default_db_path
from pam_os.runtime import PersonalMemoryRuntime
from pam_os.serialization import to_plain


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    runtime = PersonalMemoryRuntime(db_path=args.db)

    try:
        if args.command == "init":
            path = runtime.init()
            print(f"Initialized memory database: {path}")
            return 0
        if args.command == "add":
            metadata = _json_arg(args.metadata_json, default={})
            result = runtime.remember(
                args.content,
                source=args.source,
                source_ref=args.source_ref,
                metadata=metadata,
                extract=not args.no_extract,
            )
            print_json(to_plain(result))
            return 0
        if args.command == "search":
            results = runtime.search_memory(args.query, limit=args.limit, types=args.type)
            print_json(to_plain(results))
            return 0
        if args.command == "compile":
            package = runtime.compile_context(args.task, limit=args.limit)
            print(package.content)
            return 0
        if args.command == "reflect":
            package = runtime.reflect(recent=args.recent)
            print(package.content)
            return 0
        if args.command == "serve":
            from pam_os.api import serve

            serve(host=args.host, port=args.port, db_path=args.db)
            return 0
        if args.command == "mcp":
            from pam_os.mcp_server import run

            run(db_path=args.db)
            return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="memory", description="Personal Memory Runtime CLI")
    parser.add_argument("--db", default=default_db_path(), help="SQLite database path")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="Initialize the memory database")

    add = subparsers.add_parser("add", help="Add a raw event and extract memories")
    add.add_argument("content")
    add.add_argument("--source", default="manual")
    add.add_argument("--source-ref")
    add.add_argument("--metadata-json", default="{}")
    add.add_argument("--no-extract", action="store_true")

    search = subparsers.add_parser("search", help="Search memories")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--type", action="append", choices=["semantic", "episodic", "preference", "goal", "project", "style"])

    compile_cmd = subparsers.add_parser("compile", help="Compile a prompt-ready context package")
    compile_cmd.add_argument("task")
    compile_cmd.add_argument("--limit", type=int, default=12)

    reflect = subparsers.add_parser("reflect", help="Compile context from recent memories")
    reflect.add_argument("--recent", type=int, default=50)

    serve = subparsers.add_parser("serve", help="Run REST API server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)

    subparsers.add_parser("mcp", help="Run MCP stdio adapter")
    return parser


def print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def _json_arg(value: str, *, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
