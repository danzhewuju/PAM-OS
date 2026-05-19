from __future__ import annotations

from pathlib import Path
from typing import Any

from pam_os.runtime import PersonalMemoryRuntime
from pam_os.serialization import to_plain


def run(db_path: Path | str | None = None, config=None) -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise RuntimeError('MCP dependencies are missing. Install with: pip install -e ".[mcp]"') from exc

    runtime = PersonalMemoryRuntime(db_path=db_path, config=config)
    mcp = FastMCP("Personal Memory Runtime")

    @mcp.tool()
    def record_behavior_choice(
        context: str,
        chosen: list[str] | None = None,
        rejected: list[str] | None = None,
        deferred: list[str] | None = None,
        reason: str | None = None,
        source_ref: str | None = None,
    ) -> dict[str, Any]:
        """Record a user choice as behavioral evidence for long-term profile learning.

        Use this when the model presents options and the user chooses, rejects,
        or defers some of them. Behavior choices help infer stable decision
        style and preferences over time.
        """

        return to_plain(
            runtime.record_behavior_choice(
                context=context,
                chosen=chosen or [],
                rejected=rejected or [],
                deferred=deferred or [],
                reason=reason,
                source_ref=source_ref,
            )
        )

    @mcp.tool()
    def consolidate_memory(recent: int | None = None) -> dict[str, Any]:
        """Promote recent memories and behavior evidence into ultra-long-term profile traits."""

        return to_plain(runtime.consolidate_memory(recent=recent))

    @mcp.tool()
    def get_user_profile(limit: int | None = None, query: str | None = None) -> list[dict[str, Any]]:
        """Return stable ultra-long-term profile traits about the user."""

        return to_plain(runtime.get_user_profile(limit=limit, query=query))

    @mcp.tool()
    def prepare_context(
        task: str,
        conversation_summary: str | None = None,
        force: bool = False,
        limit: int | None = None,
        max_chars: int | None = None,
    ) -> dict[str, Any]:
        """Recommended pre-answer memory entrypoint.

        Call this before answering when the user asks about their preferences,
        ongoing projects, prior decisions, long-term goals, personal style, or
        asks to continue something previously discussed. Do not call it for
        generic factual or one-off questions unless force is true.
        """

        return to_plain(
            runtime.prepare_context(
                task,
                conversation_summary=conversation_summary,
                force=force,
                limit=limit,
                max_chars=max_chars,
            )
        )

    @mcp.tool()
    def capture_memory(
        content: str,
        source: str = "conversation",
        source_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Recommended post-answer memory entrypoint.

        Call this after a user reveals stable preferences, goals, project
        decisions, identity/style guidance, or corrections to prior memory. Do
        not capture transient chit-chat or generic factual questions.
        """

        return to_plain(
            runtime.capture_memory(
                content,
                source=source,
                source_ref=source_ref,
                metadata=metadata or {},
                force=force,
            )
        )

    @mcp.tool()
    def remember(
        content: str,
        source: str = "manual",
        source_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
        extract: bool = True,
    ) -> dict[str, Any]:
        """Low-level tool: store a raw event and extract structured memories.

        Prefer capture_memory for normal model-driven memory writes because it
        decides whether the content is stable enough to store.
        """

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
        """Low-level tool: search long-term memories relevant to a query.

        Prefer prepare_context before answering user-facing questions because it
        gates memory use, reranks results, and applies context budgets.
        """

        return to_plain(runtime.search_memory(query, limit=limit))

    @mcp.tool()
    def compile_context(task: str, limit: int | None = None) -> dict[str, Any]:
        """Low-level tool: compile search results into a context package.

        Prefer prepare_context for normal pre-answer memory retrieval.
        """

        return to_plain(runtime.compile_context(task, limit=limit))

    @mcp.tool()
    def reflect(recent: int = 50) -> dict[str, Any]:
        """Compile a context package from recent memories for self-reflection."""

        return to_plain(runtime.reflect(recent=recent))

    mcp.run()
