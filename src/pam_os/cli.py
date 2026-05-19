from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from pam_os.config import default_db_path, load_config
from pam_os.runtime import PersonalMemoryRuntime
from pam_os.serialization import to_plain


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)
    runtime = PersonalMemoryRuntime(db_path=args.db, config=config)

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
        if args.command == "should-use":
            decision = runtime.should_use_memory(args.task, args.conversation_summary)
            print_json(to_plain(decision))
            return 0
        if args.command == "prepare":
            prepared = runtime.prepare_context(
                args.task,
                conversation_summary=args.conversation_summary,
                force=args.force,
                limit=args.limit,
                max_chars=args.max_chars,
            )
            if args.json:
                print_json(to_plain(prepared))
            elif prepared.package:
                print(prepared.package.content)
            else:
                print_json(to_plain(prepared.decision))
            return 0
        if args.command == "capture":
            metadata = _json_arg(args.metadata_json, default={})
            result = runtime.capture_memory(
                args.content,
                source=args.source,
                source_ref=args.source_ref,
                metadata=metadata,
                force=args.force,
            )
            print_json(to_plain(result))
            return 0
        if args.command == "behavior-choice":
            event = runtime.record_behavior_choice(
                context=args.context,
                chosen=args.chosen or [],
                rejected=args.rejected or [],
                deferred=args.deferred or [],
                reason=args.reason,
                source_ref=args.source_ref,
            )
            print_json(to_plain(event))
            return 0
        if args.command == "consolidate":
            result = runtime.consolidate_memory(recent=args.recent)
            print_json(to_plain(result))
            return 0
        if args.command == "profile":
            traits = runtime.get_user_profile(limit=args.limit, query=args.query)
            print_json(to_plain(traits))
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

            serve(host=args.host or config.server.host, port=args.port or config.server.port, db_path=args.db, config=config)
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
    parser.add_argument("--config", help="Path to TOML config file. Defaults to config/pam-os.toml or PAM_OS_CONFIG.")
    parser.add_argument("--db", default=None, help=f"SQLite database path. Default: {default_db_path()}")
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

    should_use = subparsers.add_parser("should-use", help="Decide whether a task should use memory")
    should_use.add_argument("task")
    should_use.add_argument("--conversation-summary")

    prepare = subparsers.add_parser("prepare", help="Recommended pre-answer context preparation entrypoint")
    prepare.add_argument("task")
    prepare.add_argument("--conversation-summary")
    prepare.add_argument("--force", action="store_true")
    prepare.add_argument("--limit", type=int)
    prepare.add_argument("--max-chars", type=int)
    prepare.add_argument("--json", action="store_true")

    capture = subparsers.add_parser("capture", help="Recommended post-answer memory capture entrypoint")
    capture.add_argument("content")
    capture.add_argument("--source", default="conversation")
    capture.add_argument("--source-ref")
    capture.add_argument("--metadata-json", default="{}")
    capture.add_argument("--force", action="store_true")

    behavior = subparsers.add_parser("behavior-choice", help="Record a user behavior choice as profile evidence")
    behavior.add_argument("--context", required=True)
    behavior.add_argument("--chosen", action="append")
    behavior.add_argument("--rejected", action="append")
    behavior.add_argument("--deferred", action="append")
    behavior.add_argument("--reason")
    behavior.add_argument("--source-ref")

    consolidate = subparsers.add_parser("consolidate", help="Promote memories and behavior evidence into profile traits")
    consolidate.add_argument("--recent", type=int)

    profile = subparsers.add_parser("profile", help="List ultra-long-term profile traits")
    profile.add_argument("--limit", type=int)
    profile.add_argument("--query")

    compile_cmd = subparsers.add_parser("compile", help="Compile a prompt-ready context package")
    compile_cmd.add_argument("task")
    compile_cmd.add_argument("--limit", type=int)

    reflect = subparsers.add_parser("reflect", help="Compile context from recent memories")
    reflect.add_argument("--recent", type=int, default=50)

    serve = subparsers.add_parser("serve", help="Run REST API server")
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)

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
