from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pam_os.config import OrchestratorConfig
from pam_os.context import ContextCompiler
from pam_os.models import (
    CaptureResult,
    ContextUsageSummary,
    Event,
    MemoryPreview,
    MemoryUseDecision,
    PreparedContext,
    QueryIntent,
    SearchResult,
    new_id,
)
from pam_os.providers import MemoryPolicy, MemoryReranker, MemoryRetriever
from pam_os.rule_provider import RuleMemoryPolicy, RuleMemoryReranker, RuleQueryIntentClassifier, StoreMemoryRetriever
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
        query_intent_classifier: Any | None = None,
    ):
        self.store = store
        self.compiler = compiler
        self.config = config or OrchestratorConfig()
        self.profile_limit = profile_limit
        self.policy = policy or RuleMemoryPolicy(self.config)
        self.retriever = retriever or StoreMemoryRetriever(store)
        self.reranker = reranker or RuleMemoryReranker()
        self.query_intent_classifier = query_intent_classifier or RuleQueryIntentClassifier()

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
        query = self._query_for(task, conversation_summary)
        intent = self.query_intent_classifier.classify(query)
        decision = self.should_use_memory(task, conversation_summary)
        if not decision.should_use and intent.should_read:
            decision = MemoryUseDecision(True, intent.reason, intent.confidence, intent.signals)
        if not force and not decision.should_use:
            return PreparedContext(
                decision=decision,
                package=None,
                results=[],
                usage_summary=self._usage_summary(decision, package=None, results=[], profile_count=0),
            )

        profile_traits = self._profile_traits_for(query, intent)
        candidate_limit = max(budget.limit * self.config.candidate_multiplier, budget.limit)
        raw_results = self.retriever.retrieve(query, limit=candidate_limit, types=intent.memory_types or None)
        if intent.memory_types:
            intent_fallback = self.retriever.retrieve("", limit=candidate_limit, types=intent.memory_types)
            raw_results = self._merge_results(raw_results, intent_fallback)
        if not raw_results and intent.memory_types:
            raw_results = self.retriever.retrieve(query, limit=candidate_limit)
        ranked = self.reranker.rerank(query, raw_results)
        selected = self._apply_budget(ranked, budget)
        package = self.compiler.compile(task, selected, max_chars=budget.max_chars, profile_traits=profile_traits)
        self.store.save_context_package(package)
        return PreparedContext(
            decision=decision,
            package=package,
            results=selected,
            usage_summary=self._usage_summary(
                decision,
                package=package,
                results=selected,
                profile_count=len(profile_traits),
            ),
        )

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
        manual_override = force and not decision.should_use
        result_reason = decision.reason
        if manual_override:
            result_reason = f"manual override; policy would skip: {decision.reason}"
        capture_metadata = {
            **(metadata or {}),
            "capture_reason": result_reason,
            "capture_signals": decision.signals,
            "capture_policy_decision": "capture" if decision.should_use else "skip_capture",
            "capture_policy_confidence": decision.confidence,
            "manual_override": manual_override,
        }
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
                reason = result_reason
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
            result_reason,
            event=result["event"],
            memories=result["memories"],
            created_count=len(result["memories"]),
        )

    def _query_for(self, task: str, conversation_summary: str | None) -> str:
        if conversation_summary:
            return f"{task}\n{conversation_summary}"
        return task

    def _profile_traits_for(self, query: str, intent: QueryIntent | None = None):
        related = self.store.list_profile_traits(limit=self.profile_limit, query=query)
        stable = self.store.list_profile_traits(limit=max(self.profile_limit, 50))
        by_key = {trait.trait_key: trait for trait in stable[: self.profile_limit]}
        by_key.update({trait.trait_key: trait for trait in related})
        if intent and intent.trait_keys:
            by_key.update(
                {
                    trait.trait_key: trait
                    for trait in stable
                    if self._trait_matches_intent(trait.trait_key, intent.trait_keys)
                }
            )
        return sorted(
            by_key.values(),
            key=lambda item: (item.stability, item.confidence, item.evidence_count),
            reverse=True,
        )[: self.profile_limit]

    def _trait_matches_intent(self, trait_key: str, intent_keys: list[str]) -> bool:
        for key in intent_keys:
            if key.endswith(".") and trait_key.startswith(key):
                return True
            if trait_key == key:
                return True
        return False

    def _merge_results(self, primary: list[SearchResult], fallback: list[SearchResult]) -> list[SearchResult]:
        by_id = {result.memory.id: result for result in primary}
        merged = list(primary)
        for result in fallback:
            if result.memory.id in by_id:
                continue
            merged.append(result)
        return merged

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

    def _usage_summary(
        self,
        decision: MemoryUseDecision,
        *,
        package,
        results: list[SearchResult],
        profile_count: int,
    ) -> ContextUsageSummary:
        memory_type_counts: dict[str, int] = {}
        for result in results:
            memory_type_counts[result.memory.type] = memory_type_counts.get(result.memory.type, 0) + 1

        memory_count = len(results)
        context_chars = len(package.content) if package else 0
        status = "used" if package else "skipped"
        if package:
            parts = [f"PAM-OS read {memory_count} memories"]
            if profile_count:
                parts.append(f"{profile_count} profile traits")
            if memory_type_counts:
                type_summary = ", ".join(
                    f"{memory_type}:{count}" for memory_type, count in sorted(memory_type_counts.items())
                )
                parts.append(f"types {type_summary}")
            message = "; ".join(parts) + "."
        else:
            message = f"PAM-OS memory skipped: {decision.reason}."

        previews = [
            MemoryPreview(
                id=result.memory.id,
                type=result.memory.type,
                content=_preview_text(result.memory.content),
                score=result.score,
                importance=result.memory.importance,
                confidence=result.memory.confidence,
                tags=result.memory.tags[:8],
            )
            for result in results[:5]
        ]
        return ContextUsageSummary(
            status=status,
            message=message,
            reason=decision.reason,
            confidence=decision.confidence,
            package_id=package.id if package else None,
            memory_count=memory_count,
            profile_count=profile_count,
            memory_type_counts=memory_type_counts,
            memory_ids=[result.memory.id for result in results],
            previews=previews,
            context_chars=context_chars,
            full_context_available=package is not None,
        )


def _preview_text(value: str, *, max_chars: int = 180) -> str:
    compact = " ".join(value.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."
