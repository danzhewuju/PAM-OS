from __future__ import annotations

import json

from pam_os.mcp import PamOsMcpServer
from pam_os.runtime import PersonalMemoryRuntime


def test_mcp_lists_memory_tools(tmp_path):
    server = PamOsMcpServer(PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3"))

    response = server.handle_message({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response is not None
    tools = response["result"]["tools"]
    tool_names = {tool["name"] for tool in tools}
    assert "prepare_context" in tool_names
    assert "capture_memory" in tool_names
    assert "get_profile" in tool_names
    assert "clear_memory" in tool_names


def test_mcp_calls_capture_and_prepare_context(tmp_path):
    server = PamOsMcpServer(PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3"))

    capture = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "capture_memory",
                "arguments": {
                    "content": "我决定 PAM-OS 中期先做 Codex plugin + MCP adapter。",
                    "force": True,
                },
            },
        }
    )
    assert capture is not None
    assert capture["result"]["structuredContent"]["should_capture"] is True

    prepared = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "prepare_context",
                "arguments": {"task": "我继续做 PAM-OS Codex 集成，下一步怎么做？", "force": True},
            },
        }
    )

    assert prepared is not None
    payload = prepared["result"]["structuredContent"]
    assert payload["package"] is not None
    assert "PAM-OS" in payload["package"]["content"]
    text_payload = json.loads(prepared["result"]["content"][0]["text"])
    assert text_payload["package"]["memory_ids"]


def test_mcp_rejects_unknown_tool(tmp_path):
    server = PamOsMcpServer(PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3"))

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "does_not_exist", "arguments": {}},
        }
    )

    assert response is not None
    assert response["error"]["code"] == -32602


def test_mcp_clear_memory_requires_confirmation(tmp_path):
    server = PamOsMcpServer(PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3"))

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "clear_memory", "arguments": {}},
        }
    )

    assert response is not None
    assert response["error"]["code"] == -32602
    assert "confirm=true" in response["error"]["message"]


def test_mcp_clear_memory_deletes_stored_data(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")
    runtime.capture_memory("我偏好 self-host、开源、可控系统。", force=True)
    server = PamOsMcpServer(runtime)

    response = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "clear_memory", "arguments": {"confirm": True}},
        }
    )

    assert response is not None
    payload = response["result"]["structuredContent"]
    assert payload["deleted_counts"]["events"] == 1
    assert payload["deleted_counts"]["memories"] >= 1
    assert payload["storage_stats"]["tables"]["events"]["count"] == 0
    assert payload["storage_stats"]["tables"]["memories"]["count"] == 0
