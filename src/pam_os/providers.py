from __future__ import annotations

from typing import Any, Protocol

from pam_os.models import ConsolidationResult, Memory, MemoryUseDecision, SearchResult


class MemoryPolicy(Protocol):
    def decide_read(self, task: str, conversation_summary: str | None = None) -> MemoryUseDecision:
        ...

    def decide_capture(self, content: str, metadata: dict[str, Any] | None = None) -> MemoryUseDecision:
        ...


class MemoryExtractor(Protocol):
    def extract(self, event_id: str, content: str, metadata: dict[str, Any]) -> list[Memory]:
        ...


class MemoryRetriever(Protocol):
    def retrieve(
        self,
        query: str,
        *,
        limit: int,
        types: list[str] | None = None,
        min_importance: float = 0.0,
        min_confidence: float = 0.0,
    ) -> list[SearchResult]:
        ...


class MemoryReranker(Protocol):
    def rerank(self, query: str, results: list[SearchResult]) -> list[SearchResult]:
        ...


class ProfileConsolidator(Protocol):
    def consolidate(self, *, recent: int = 100) -> ConsolidationResult:
        ...
