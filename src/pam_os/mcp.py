from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from typing import Any, TextIO

from pam_os.config import default_db_path, load_config
from pam_os.runtime import PersonalMemoryRuntime
from pam_os.serialization import to_plain
from pam_os.version import __version__


JSONRPC_VERSION = "2.0"
MCP_PROTOCOL_VERSION = "2025-06-18"


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str, data: Any | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


class PamOsMcpServer:
    def __init__(self, runtime: PersonalMemoryRuntime):
        self.runtime = runtime
        self._tools: dict[str, Callable[[dict[str, Any]], Any]] = {
            "prepare_context": self._prepare_context,
            "capture_memory": self._capture_memory,
            "record_behavior_choice": self._record_behavior_choice,
            "observe_turn": self._observe_turn,
            "consolidate_memory": self._consolidate_memory,
            "get_profile": self._get_profile,
            "search_memory": self._search_memory,
            "inspect_memory": self._inspect_memory,
            "get_storage_stats": self._get_storage_stats,
            "clear_memory": self._clear_memory,
        }

    def handle_message(self, message: dict[str, Any]) -> dict[str, Any] | None:
        request_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or {}

        if method is None:
            return self._error_response(request_id, -32600, "method is required")
        if not isinstance(method, str):
            return self._error_response(request_id, -32600, "method must be a string")
        if params is not None and not isinstance(params, dict):
            return self._error_response(request_id, -32602, "params must be an object")

        try:
            result = self._dispatch(method, params)
        except JsonRpcError as exc:
            return self._error_response(request_id, exc.code, exc.message, exc.data)
        except Exception as exc:
            return self._error_response(request_id, -32603, str(exc))

        if request_id is None:
            return None
        return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}

    def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        if method == "initialize":
            return {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "pam-os-memory", "version": __version__},
            }
        if method == "notifications/initialized":
            return {}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": tool_definitions()}
        if method == "tools/call":
            return self._call_tool(params)
        if method in {"resources/list", "prompts/list"}:
            return {method.split("/", maxsplit=1)[0]: []}
        raise JsonRpcError(-32601, f"method not found: {method}")

    def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str) or not name:
            raise JsonRpcError(-32602, "tools/call requires a tool name")
        if not isinstance(arguments, dict):
            raise JsonRpcError(-32602, "tools/call arguments must be an object")

        handler = self._tools.get(name)
        if handler is None:
            raise JsonRpcError(-32602, f"unknown tool: {name}")

        result = to_plain(handler(arguments))
        if isinstance(result, list):
            result = {"items": result}
        return {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}],
            "structuredContent": result,
        }

    def _prepare_context(self, arguments: dict[str, Any]) -> Any:
        task = _required_str(arguments, "task")
        return self.runtime.prepare_context(
            task,
            conversation_summary=_optional_str(arguments, "conversation_summary"),
            force=bool(arguments.get("force", False)),
            limit=_optional_int(arguments, "limit"),
            max_chars=_optional_int(arguments, "max_chars"),
        )

    def _capture_memory(self, arguments: dict[str, Any]) -> Any:
        content = _required_str(arguments, "content")
        metadata = arguments.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise JsonRpcError(-32602, "metadata must be an object")
        return self.runtime.capture_memory(
            content,
            source=_optional_str(arguments, "source") or "conversation",
            source_ref=_optional_str(arguments, "source_ref"),
            metadata=metadata,
            force=bool(arguments.get("force", False)),
        )

    def _record_behavior_choice(self, arguments: dict[str, Any]) -> Any:
        return self.runtime.record_behavior_choice(
            context=_required_str(arguments, "context"),
            chosen=_optional_str_list(arguments, "chosen"),
            rejected=_optional_str_list(arguments, "rejected"),
            deferred=_optional_str_list(arguments, "deferred"),
            reason=_optional_str(arguments, "reason"),
            source_ref=_optional_str(arguments, "source_ref"),
        )

    def _observe_turn(self, arguments: dict[str, Any]) -> Any:
        return self.runtime.observe_turn(
            user_message=_required_str(arguments, "user_message"),
            assistant_message=_optional_str(arguments, "assistant_message") or "",
            conversation_summary=_optional_str(arguments, "conversation_summary"),
            source_ref=_optional_str(arguments, "source_ref"),
            auto_capture=bool(arguments.get("auto_capture", True)),
            auto_learn_policy=bool(arguments.get("auto_learn_policy", True)),
        )

    def _consolidate_memory(self, arguments: dict[str, Any]) -> Any:
        return self.runtime.consolidate_memory(recent=_optional_int(arguments, "recent"))

    def _get_profile(self, arguments: dict[str, Any]) -> Any:
        return self.runtime.get_user_profile(
            limit=_optional_int(arguments, "limit"),
            query=_optional_str(arguments, "query"),
        )

    def _search_memory(self, arguments: dict[str, Any]) -> Any:
        return self.runtime.search_memory(
            _required_str(arguments, "query"),
            limit=_optional_int(arguments, "limit") or 10,
            types=_optional_str_list(arguments, "types") or None,
        )

    def _inspect_memory(self, arguments: dict[str, Any]) -> Any:
        return self.runtime.inspect_memory(
            table=_optional_str(arguments, "table") or "all",
            limit=_optional_int(arguments, "limit") or 20,
            query=_optional_str(arguments, "query"),
        )

    def _get_storage_stats(self, arguments: dict[str, Any]) -> Any:
        if arguments:
            raise JsonRpcError(-32602, "get_storage_stats does not accept arguments")
        return self.runtime.get_storage_stats()

    def _clear_memory(self, arguments: dict[str, Any]) -> Any:
        if arguments.get("confirm") is not True:
            raise JsonRpcError(-32602, "clear_memory requires confirm=true")
        return self.runtime.clear_memory()

    def _error_response(
        self,
        request_id: Any,
        code: int,
        message: str,
        data: Any | None = None,
    ) -> dict[str, Any]:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "error": error}


def serve_stdio(server: PamOsMcpServer, stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
            if not isinstance(message, dict):
                raise JsonRpcError(-32600, "message must be an object")
            response = server.handle_message(message)
        except json.JSONDecodeError as exc:
            response = {"jsonrpc": JSONRPC_VERSION, "id": None, "error": {"code": -32700, "message": str(exc)}}
        except JsonRpcError as exc:
            response = {"jsonrpc": JSONRPC_VERSION, "id": None, "error": {"code": exc.code, "message": exc.message}}

        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            stdout.flush()


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "prepare_context",
            "description": "Prepare prompt-ready PAM-OS memory context for a user task.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "task": {"type": "string"},
                    "conversation_summary": {"type": "string"},
                    "force": {"type": "boolean", "default": False},
                    "limit": {"type": "integer", "minimum": 1},
                    "max_chars": {"type": "integer", "minimum": 1},
                },
                "required": ["task"],
                "additionalProperties": False,
            },
        },
        {
            "name": "capture_memory",
            "description": "Capture stable user preferences, goals, project decisions, style guidance, or corrections.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "source": {"type": "string", "default": "conversation"},
                    "source_ref": {"type": "string"},
                    "metadata": {"type": "object", "additionalProperties": True},
                    "force": {"type": "boolean", "default": False},
                },
                "required": ["content"],
                "additionalProperties": False,
            },
        },
        {
            "name": "record_behavior_choice",
            "description": "Record a user choice as behavior evidence for future profile consolidation.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "context": {"type": "string"},
                    "chosen": {"type": "array", "items": {"type": "string"}},
                    "rejected": {"type": "array", "items": {"type": "string"}},
                    "deferred": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                    "source_ref": {"type": "string"},
                },
                "required": ["context"],
                "additionalProperties": False,
            },
        },
        {
            "name": "observe_turn",
            "description": "Observe a completed chat turn and apply conservative automatic memory/policy learning with audit traces.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "user_message": {"type": "string"},
                    "assistant_message": {"type": "string"},
                    "conversation_summary": {"type": "string"},
                    "source_ref": {"type": "string"},
                    "auto_capture": {"type": "boolean", "default": True},
                    "auto_learn_policy": {"type": "boolean", "default": True},
                },
                "required": ["user_message"],
                "additionalProperties": False,
            },
        },
        {
            "name": "consolidate_memory",
            "description": "Promote recent memories and behavior events into stable profile traits.",
            "inputSchema": {
                "type": "object",
                "properties": {"recent": {"type": "integer", "minimum": 1}},
                "additionalProperties": False,
            },
        },
        {
            "name": "get_profile",
            "description": "Read stable user profile traits from PAM-OS.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1},
                    "query": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "search_memory",
            "description": "Search stored PAM-OS memories.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "default": 10},
                    "types": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "inspect_memory",
            "description": "Inspect PAM-OS storage tables and diagnostic details.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "default": "all"},
                    "limit": {"type": "integer", "minimum": 1, "default": 20},
                    "query": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "get_storage_stats",
            "description": "Return PAM-OS storage statistics.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "clear_memory",
            "description": "Clear all PAM-OS memory data. Requires confirm=true.",
            "inputSchema": {
                "type": "object",
                "properties": {"confirm": {"type": "boolean"}},
                "required": ["confirm"],
                "additionalProperties": False,
            },
        },
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pam-os-mcp", description="PAM-OS MCP stdio server")
    parser.add_argument("--config", help="Path to TOML config file. Defaults to config/pam-os.toml or PAM_OS_CONFIG.")
    parser.add_argument("--db", default=None, help=f"SQLite database path. Default: {default_db_path()}")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    runtime = PersonalMemoryRuntime(db_path=args.db, config=config)
    serve_stdio(PamOsMcpServer(runtime))
    return 0


def _required_str(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise JsonRpcError(-32602, f"{key} must be a non-empty string")
    return value


def _optional_str(arguments: dict[str, Any], key: str) -> str | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise JsonRpcError(-32602, f"{key} must be a string")
    return value


def _optional_int(arguments: dict[str, Any], key: str) -> int | None:
    value = arguments.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise JsonRpcError(-32602, f"{key} must be an integer")
    if value < 1:
        raise JsonRpcError(-32602, f"{key} must be >= 1")
    return value


def _optional_str_list(arguments: dict[str, Any], key: str) -> list[str]:
    value = arguments.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise JsonRpcError(-32602, f"{key} must be an array of strings")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
