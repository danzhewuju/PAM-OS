from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pam_os.config import OrchestratorConfig
from pam_os.context import ContextCompiler
from pam_os.models import CaptureResult, MemoryUseDecision, PreparedContext, SearchResult
from pam_os.store import MemoryStore


READ_SIGNALS = {
    "personal_reference": ["我", "我的", "偏好", "风格", "目标", "长期", "之前", "上次", "继续", "记得"],
    "project_reference": ["项目", "MVP", "Personal AI Memory OS", "PAM-OS", "Memory OS", "当前阶段"],
    "preference_reference": ["喜欢", "不喜欢", "倾向", "符合我", "按我的", "不要", "希望"],
    "history_reference": ["之前说过", "历史", "决策", "背景", "上下文", "继续做"],
}

CAPTURE_SIGNALS = {
    "preference": ["我偏好", "我喜欢", "我不喜欢", "我倾向", "更希望", "不要一开始"],
    "goal": ["我的目标", "我希望", "下一步", "计划", "准备做"],
    "project": ["项目", "决定", "当前阶段", "先用", "不引入", "MVP"],
    "style": ["回答风格", "以后回答", "直接", "工程化", "少营销"],
}

GENERIC_QUESTION_MARKERS = ["怎么排序", "是什么", "解释一下", "语法", "报错", "天气", "新闻"]


@dataclass(frozen=True)
class ContextBudget:
    limit: int = 12
    max_chars: int = 4000
    per_type_limits: dict[str, int] | None = None

    def limit_for(self, memory_type: str) -> int:
        limits = self.per_type_limits or {
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
    ):
        self.store = store
        self.compiler = compiler
        self.config = config or OrchestratorConfig()
        self.profile_limit = profile_limit

    def should_use_memory(self, task: str, conversation_summary: str | None = None) -> MemoryUseDecision:
        text = f"{task}\n{conversation_summary or ''}".strip()
        if not text:
            return MemoryUseDecision(False, "empty task", 0.0, [])

        signals = self._matched_signals(text, READ_SIGNALS)
        generic_hits = [marker for marker in GENERIC_QUESTION_MARKERS if marker in text]
        if generic_hits and not signals:
            return MemoryUseDecision(False, "generic factual or one-off question", 0.75, generic_hits)

        confidence = min(0.95, 0.25 + 0.18 * len(signals))
        if "我" in text or "我的" in text:
            confidence += 0.1
        if "继续" in text or "之前" in text:
            confidence += 0.12
        confidence = min(confidence, 0.95)

        if confidence >= self.config.memory_use_threshold:
            return MemoryUseDecision(True, "task appears user/project/history dependent", confidence, signals)
        return MemoryUseDecision(False, "no strong memory-use signal", max(confidence, 0.35), signals)

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
        raw_results = self.store.search_memories(query, limit=candidate_limit)
        ranked = self._rerank(raw_results)
        selected = self._apply_budget(ranked, budget)
        package = self.compiler.compile(task, selected, max_chars=budget.max_chars, profile_traits=profile_traits)
        self.store.save_context_package(package)
        return PreparedContext(decision=decision, package=package, results=selected)

    def should_capture_memory(self, content: str, metadata: dict[str, Any] | None = None) -> MemoryUseDecision:
        text = content.strip()
        if not text:
            return MemoryUseDecision(False, "empty content", 0.0, [])

        signals = self._matched_signals(text, CAPTURE_SIGNALS)
        metadata = metadata or {}
        if metadata.get("explicit_memory") is True:
            signals.append("explicit_memory")

        confidence = min(0.95, 0.2 + 0.18 * len(signals))
        if any(marker in text for marker in ["决定", "偏好", "目标", "不引入", "先用"]):
            confidence += 0.15
        confidence = min(confidence, 0.95)

        if confidence >= self.config.capture_threshold:
            return MemoryUseDecision(True, "content contains stable user/project information", confidence, signals)
        return MemoryUseDecision(False, "content looks transient", max(confidence, 0.3), signals)

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
        result = remember_func(
            content,
            source=source,
            source_ref=source_ref,
            metadata={**(metadata or {}), "capture_reason": decision.reason, "capture_signals": decision.signals},
            extract=True,
        )
        return CaptureResult(True, decision.reason, event=result["event"], memories=result["memories"])

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

    def _rerank(self, results: list[SearchResult]) -> list[SearchResult]:
        now = datetime.now(timezone.utc)
        reranked: list[SearchResult] = []
        for result in results:
            memory = result.memory
            relevance = self._normalize_relevance(result.score)
            recency = self._recency_score(memory.updated_at, now)
            stability = 0.85 if memory.type in {"preference", "goal", "project", "style"} else 0.45
            score = (
                relevance * 0.45
                + memory.importance * 0.25
                + memory.confidence * 0.15
                + recency * 0.10
                + stability * 0.05
            )
            reranked.append(SearchResult(memory=memory, score=score))
        return sorted(reranked, key=lambda item: item.score, reverse=True)

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

    def _matched_signals(self, text: str, signal_map: dict[str, list[str]]) -> list[str]:
        signals: list[str] = []
        for signal, markers in signal_map.items():
            if any(marker.lower() in text.lower() for marker in markers):
                signals.append(signal)
        return signals

    def _normalize_relevance(self, raw_score: float) -> float:
        if raw_score < 0:
            return min(1.0, abs(raw_score) * 100000)
        return max(0.0, min(1.0, raw_score))

    def _recency_score(self, updated_at: str, now: datetime) -> float:
        try:
            updated = datetime.fromisoformat(updated_at)
        except ValueError:
            return 0.3
        age_days = max(0.0, (now - updated).total_seconds() / 86400)
        return math.exp(-age_days / 30)
