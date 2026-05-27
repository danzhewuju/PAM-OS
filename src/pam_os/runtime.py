from __future__ import annotations

from pathlib import Path
from typing import Any

from pam_os.adaptive_policy import AdaptiveMemoryPolicy, PolicySignalLearner
from pam_os.config import AppConfig, default_db_path, load_config
from pam_os.context import ContextCompiler
from pam_os.extractor import RuleBasedExtractor
from pam_os.models import BehaviorEvent, ContextPackage, Event, Memory, SearchResult, StorageStats, new_id
from pam_os.orchestrator import ContextBudget, MemoryOrchestrator
from pam_os.providers import MemoryExtractor, MemoryPolicy, MemoryReranker, MemoryRetriever, ProfileConsolidator
from pam_os.rule_provider import RuleProfileConsolidator
from pam_os.store import MemoryStore


class PersonalMemoryRuntime:
    def __init__(
        self,
        db_path: Path | str | None = None,
        extractor: MemoryExtractor | None = None,
        policy: MemoryPolicy | None = None,
        retriever: MemoryRetriever | None = None,
        reranker: MemoryReranker | None = None,
        consolidator: ProfileConsolidator | None = None,
        config: AppConfig | None = None,
    ):
        self.config = config or load_config()
        self.store = MemoryStore(db_path or default_db_path(self.config), retrieval_config=self.config.retrieval)
        self.extractor = extractor or RuleBasedExtractor()
        self.compiler = ContextCompiler()
        self.policy_learner = PolicySignalLearner(self.store)
        policy = policy or AdaptiveMemoryPolicy(self.store, config=self.config.orchestrator)
        self.orchestrator = MemoryOrchestrator(
            self.store,
            self.compiler,
            config=self.config.orchestrator,
            profile_limit=self.config.context.profile_limit,
            policy=policy,
            retriever=retriever,
            reranker=reranker,
        )
        self.consolidator = consolidator or RuleProfileConsolidator(self.store, config=self.config.consolidation)

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
        limit: int | None = None,
        min_importance: float = 0.0,
        min_confidence: float = 0.0,
    ) -> ContextPackage:
        results = self.search_memory(
            task,
            limit=limit or self.config.context.default_limit,
            min_importance=min_importance,
            min_confidence=min_confidence,
        )
        package = self.compiler.compile(task, results)
        self.store.save_context_package(package)
        return package

    def should_use_memory(self, task: str, conversation_summary: str | None = None):
        return self.orchestrator.should_use_memory(task, conversation_summary)

    def prepare_context(
        self,
        task: str,
        *,
        conversation_summary: str | None = None,
        force: bool = False,
        limit: int | None = None,
        max_chars: int | None = None,
    ):
        return self.orchestrator.prepare_context(
            task,
            conversation_summary=conversation_summary,
            force=force,
            budget=ContextBudget(
                limit=limit or self.config.context.default_limit,
                max_chars=max_chars or self.config.context.max_chars,
            ),
        )

    def should_capture_memory(self, content: str, metadata: dict[str, Any] | None = None):
        return self.orchestrator.should_capture_memory(content, metadata)

    def capture_memory(
        self,
        content: str,
        *,
        source: str = "conversation",
        source_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
        force: bool = False,
    ):
        return self.orchestrator.capture_memory(
            content,
            remember_func=self.remember,
            source=source,
            source_ref=source_ref,
            metadata=metadata,
            force=force,
        )

    def record_behavior_choice(
        self,
        *,
        context: str,
        chosen: list[str] | None = None,
        rejected: list[str] | None = None,
        deferred: list[str] | None = None,
        reason: str | None = None,
        source_ref: str | None = None,
    ) -> BehaviorEvent:
        if not context.strip():
            raise ValueError("context must not be empty")
        event = BehaviorEvent(
            id=new_id("beh"),
            context=context.strip(),
            chosen=chosen or [],
            rejected=rejected or [],
            deferred=deferred or [],
            reason=reason,
            source_ref=source_ref,
        )
        self.store.add_behavior_event(event)
        return event

    def consolidate_memory(self, *, recent: int | None = None):
        return self.consolidator.consolidate(recent=recent or self.config.consolidation.recent_limit)

    def get_user_profile(self, *, limit: int | None = None, query: str | None = None):
        return self.store.list_profile_traits(limit=limit or self.config.profile.default_limit, query=query)

    def learn_policy_signal(
        self,
        *,
        signal_type: str,
        pattern: str,
        normalized_intent: str,
        action: str,
        scope: str = "general",
        confidence: float = 0.66,
        source: str = "user_feedback",
    ):
        return self.policy_learner.learn_signal(
            signal_type=signal_type,
            pattern=pattern,
            normalized_intent=normalized_intent,
            action=action,
            scope=scope,
            confidence=confidence,
            source=source,
        )

    def learn_policy_signal_from_text(
        self,
        *,
        signal_type: str,
        text: str,
        normalized_intent: str,
        action: str,
        scope: str = "general",
        confidence: float = 0.66,
        source: str = "user_feedback",
        metadata: dict[str, Any] | None = None,
    ):
        return self.policy_learner.learn_from_text(
            signal_type=signal_type,
            text=text,
            normalized_intent=normalized_intent,
            action=action,
            scope=scope,
            confidence=confidence,
            source=source,
            metadata=metadata,
        )

    def reinforce_policy_signal(
        self,
        *,
        signal_type: str,
        pattern: str,
        action: str,
        supported: bool,
    ):
        return self.policy_learner.reinforce_signal(
            signal_type=signal_type,
            pattern=pattern,
            action=action,
            supported=supported,
        )

    def list_policy_signals(
        self,
        *,
        signal_type: str | None = None,
        action: str | None = None,
        statuses: list[str] | None = None,
        limit: int = 50,
    ):
        return self.store.list_policy_signals(
            signal_type=signal_type,
            action=action,
            statuses=statuses,
            limit=limit,
        )

    def reflect(self, *, recent: int = 50) -> ContextPackage:
        memories = self.store.recent_memories(limit=recent)
        results = [
            SearchResult(memory=memory, score=memory.importance * memory.confidence)
            for memory in memories
        ]
        package = self.compiler.compile("Reflect on recent memories and summarize stable context.", results)
        self.store.save_context_package(package)
        return package

    def get_storage_stats(self) -> StorageStats:
        return self.store.get_storage_stats()

    def clear_memory(self) -> dict[str, Any]:
        deleted_counts = self.store.clear_all()
        return {
            "deleted_counts": deleted_counts,
            "storage_stats": self.get_storage_stats(),
        }

    def inspect_memory(self, *, table: str = "all", limit: int = 20, query: str | None = None) -> dict[str, Any]:
        return self.store.inspect_memory(table=table, limit=limit, query=query)
