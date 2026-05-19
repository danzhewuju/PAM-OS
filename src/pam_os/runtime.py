from __future__ import annotations

from pathlib import Path
from typing import Any

from pam_os.config import default_db_path
from pam_os.context import ContextCompiler
from pam_os.extractor import Extractor, RuleBasedExtractor
from pam_os.models import ContextPackage, Event, Memory, SearchResult, new_id
from pam_os.store import MemoryStore


class PersonalMemoryRuntime:
    def __init__(self, db_path: Path | str | None = None, extractor: Extractor | None = None):
        self.store = MemoryStore(db_path or default_db_path())
        self.extractor = extractor or RuleBasedExtractor()
        self.compiler = ContextCompiler()

    @property
    def db_path(self) -> Path:
        return self.store.db_path

    def init(self) -> Path:
        self.store.init()
        return self.store.db_path

    def remember(
        self,
        content: str,
        *,
        source: str = "manual",
        source_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
        extract: bool = True,
    ) -> dict[str, Any]:
        if not content.strip():
            raise ValueError("content must not be empty")
        event = Event(
            id=new_id("evt"),
            source=source,
            source_ref=source_ref,
            content=content.strip(),
            metadata=metadata or {},
        )
        self.store.add_event(event)
        memories: list[Memory] = []
        if extract:
            memories = self.extractor.extract(event.id, event.content, event.metadata)
            self.store.add_memories(memories)
        return {"event": event, "memories": memories}

    def search_memory(
        self,
        query: str,
        *,
        limit: int = 10,
        types: list[str] | None = None,
        min_importance: float = 0.0,
        min_confidence: float = 0.0,
    ) -> list[SearchResult]:
        return self.store.search_memories(
            query,
            limit=limit,
            types=types,
            min_importance=min_importance,
            min_confidence=min_confidence,
        )

    def compile_context(
        self,
        task: str,
        *,
        limit: int = 12,
        min_importance: float = 0.0,
        min_confidence: float = 0.0,
    ) -> ContextPackage:
        results = self.search_memory(
            task,
            limit=limit,
            min_importance=min_importance,
            min_confidence=min_confidence,
        )
        package = self.compiler.compile(task, results)
        self.store.save_context_package(package)
        return package

    def reflect(self, *, recent: int = 50) -> ContextPackage:
        memories = self.store.recent_memories(limit=recent)
        results = [
            SearchResult(memory=memory, score=memory.importance * memory.confidence)
            for memory in memories
        ]
        package = self.compiler.compile("Reflect on recent memories and summarize stable context.", results)
        self.store.save_context_package(package)
        return package
