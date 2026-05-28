from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pam_os.config import OrchestratorConfig
from pam_os.context import ContextCompiler
from pam_os.models import CaptureResult, Event, MemoryUseDecision, PreparedContext, SearchResult, new_id
from pam_os.providers import MemoryPolicy, MemoryReranker, MemoryRetriever
from pam_os.rule_provider import RuleMemoryPolicy, RuleMemoryReranker, StoreMemoryRetriever
from pam_os.store import MemoryStore


@dataclass(frozen=True)
class ContextBudget:
    limit: int = 12
    max_chars: int = 4000
    per_type_limits: dict[str, int] | None = None

    def limit_for(self, memory_type: str) -> int:
        limits = self.per_type_limits or {
            "identity": 2,
            "preference": 4,
            "project": 4,
            "goal": 3,
            "style": 3,
            "episodic": 3,
            "semantic": 3,
        }
        return limits.get(memory_type, 2)


class MemoryOrchestrator:
    def __init__(
        self,
        store: MemoryStore,
        compiler: ContextCompiler,
        *,
        config: OrchestratorConfig | None = None,
        profile_limit: int = 8,
        policy: MemoryPolicy | None = None,
        retriever: MemoryRetriever | None = None,
        reranker: MemoryReranker | None = None,
    ):
        self.store = store
        self.compiler = compiler
        self.config = config or OrchestratorConfig()
        self.profile_limit = profile_limit
        self.policy = policy or RuleMemoryPolicy(self.config)
        self.retriever = retriever or StoreMemoryRetriever(store)
        self.reranker = reranker or RuleMemoryReranker()

    def should_use_memory(self, task: str, conversation_summary: str | None = None) -> MemoryUseDecision:
        return self.policy.decide_read(task, conversation_summary)

    def prepare_context(
        self,
        task: str,
        *,
        conversation_summary: str | None = None,
        force: bool = False,
        budget: ContextBudget | None = None,
    ) -> PreparedContext:
        budget = budget or ContextBudget()
        decision = self.should_use_memory(task, conversation_summary)
        if not force and not decision.should_use:
            return PreparedContext(decision=decision, package=None, results=[])

        query = self._query_for(task, conversation_summary)
        profile_traits = self._profile_traits_for(query)
        candidate_limit = max(budget.limit * self.config.candidate_multiplier, budget.limit)
        raw_results = self.retriever.retrieve(query, limit=candidate_limit)
        ranked = self.reranker.rerank(query, raw_results)
        selected = self._apply_budget(ranked, budget)
        package = self.compiler.compile(task, selected, max_chars=budget.max_chars, profile_traits=profile_traits)
        self.store.save_context_package(package)
        return PreparedContext(decision=decision, package=package, results=selected)

    def should_capture_memory(self, content: str, metadata: dict[str, Any] | None = None) -> MemoryUseDecision:
        return self.policy.decide_capture(content, metadata)

    def capture_memory(
        self,
        content: str,
        *,
        remember_func,
        source: str = "conversation",
        source_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
        force: bool = False,
    ) -> CaptureResult:
        decision = self.should_capture_memory(content, metadata)
        if not force and not decision.should_use:
            return CaptureResult(False, decision.reason)
        capture_metadata = {**(metadata or {}), "capture_reason": decision.reason, "capture_signals": decision.signals}
        if hasattr(remember_func, "__self__") and getattr(remember_func, "__self__", None) is not None:
            runtime = remember_func.__self__
            extractor = getattr(runtime, "extractor", None)
            if extractor is not None:
                event = Event(
                    id=new_id("evt"),
                    source=source,
                    source_ref=source_ref,
                    content=content.strip(),
                    metadata=capture_metadata,
                )
                self.store.add_event(event)
                candidates = extractor.extract(event.id, event.content, event.metadata)
                memories, created_count, updated_count = self.store.upsert_deduped_memories(candidates)
                reason = decision.reason
                if updated_count and not created_count:
                    reason = f"{reason}; reinforced existing memory"
                elif updated_count:
                    reason = f"{reason}; deduped {updated_count} existing memory item(s)"
                return CaptureResult(
                    True,
                    reason,
                    event=event,
                    memories=memories,
                    created_count=created_count,
                    updated_count=updated_count,
                )

        result = remember_func(
            content,
            source=source,
            source_ref=source_ref,
            metadata=capture_metadata,
            extract=True,
        )
        return CaptureResult(
            True,
            decision.reason,
            event=result["event"],
            memories=result["memories"],
            created_count=len(result["memories"]),
        )

    def _query_for(self, task: str, conversation_summary: str | None) -> str:
        if conversation_summary:
            return f"{task}\n{conversation_summary}"
        return task

    def _profile_traits_for(self, query: str):
        related = self.store.list_profile_traits(limit=self.profile_limit, query=query)
        stable = self.store.list_profile_traits(limit=self.profile_limit)
        by_key = {trait.trait_key: trait for trait in stable}
        by_key.update({trait.trait_key: trait for trait in related})
        return sorted(
            by_key.values(),
            key=lambda item: (item.stability, item.confidence, item.evidence_count),
            reverse=True,
        )[: self.profile_limit]

    def _apply_budget(self, results: list[SearchResult], budget: ContextBudget) -> list[SearchResult]:
        selected: list[SearchResult] = []
        type_counts: dict[str, int] = {}
        chars = 0
        for result in results:
            memory_type = result.memory.type
            if type_counts.get(memory_type, 0) >= budget.limit_for(memory_type):
                continue
            next_chars = chars + len(result.memory.content)
            if selected and next_chars > budget.max_chars:
                continue
            selected.append(result)
            type_counts[memory_type] = type_counts.get(memory_type, 0) + 1
            chars = next_chars
            if len(selected) >= budget.limit:
                break
        return selected
