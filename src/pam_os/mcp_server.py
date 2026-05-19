from __future__ import annotations

from pathlib import Path
from typing import Any

from pam_os.runtime import PersonalMemoryRuntime
from pam_os.serialization import to_plain


def run(db_path: Path | str | None = None) -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError('MCP dependencies are missing. Install with: pip install -e ".[mcp]"') from exc

    runtime = PersonalMemoryRuntime(db_path=db_path)
    mcp = FastMCP("Personal Memory Runtime")

    @mcp.tool()
    def remember(
        content: str,
        source: str = "manual",
        source_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
        extract: bool = True,
    ) -> dict[str, Any]:
        """Store a raw event and extract structured long-term memories."""

        return to_plain(
            runtime.remember(
                content,
                source=source,
                source_ref=source_ref,
                metadata=metadata or {},
                extract=extract,
            )
        )

    @mcp.tool()
    def search_memory(query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search long-term memories relevant to a query."""

        return to_plain(runtime.search_memory(query, limit=limit))

    @mcp.tool()
    def compile_context(task: str, limit: int = 12) -> dict[str, Any]:
        """Compile relevant memories into a prompt-ready context package."""

        return to_plain(runtime.compile_context(task, limit=limit))

    @mcp.tool()
    def reflect(recent: int = 50) -> dict[str, Any]:
        """Compile a context package from recent memories for self-reflection."""

        return to_plain(runtime.reflect(recent=recent))

    mcp.run()
