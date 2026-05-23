from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from pam_os.config import ConsolidationConfig, OrchestratorConfig
from pam_os.models import (
    BehaviorEvent,
    ConsolidationResult,
    Memory,
    MemoryUseDecision,
    ProfileEvidence,
    ProfileTrait,
    SearchResult,
    new_id,
    now_iso,
)
from pam_os.store import MemoryStore


READ_SIGNALS = {
    "personal_reference": ["我", "我的", "偏好", "风格", "目标", "长期", "之前", "上次", "继续", "记得"],
    "project_reference": ["项目", "当前项目", "当前阶段", "project", "current project"],
    "preference_reference": ["喜欢", "不喜欢", "倾向", "符合我", "按我的", "不要", "希望"],
    "history_reference": ["之前说过", "历史", "决策", "背景", "上下文", "继续做"],
}

CAPTURE_SIGNALS = {
    "preference": ["我偏好", "我喜欢", "我不喜欢", "我倾向", "更希望", "不要一开始"],
    "goal": ["我的目标", "我希望", "下一步", "计划", "准备做"],
    "project": ["项目", "决定", "当前项目", "当前阶段", "先用", "不引入"],
    "style": ["回答风格", "以后回答", "直接", "工程化", "少营销"],
}

GENERIC_QUESTION_MARKERS = ["怎么排序", "是什么", "解释一下", "语法", "报错", "天气", "新闻"]


class RuleMemoryPolicy:
    def __init__(self, config: OrchestratorConfig | None = None):
        self.config = config or OrchestratorConfig()

    def decide_read(self, task: str, conversation_summary: str | None = None) -> MemoryUseDecision:
        text = f"{task}\n{conversation_summary or ''}".strip()
        if not text:
            return MemoryUseDecision(False, "empty task", 0.0, [])

        signals = _matched_signals(text, READ_SIGNALS)
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

    def decide_capture(self, content: str, metadata: dict[str, Any] | None = None) -> MemoryUseDecision:
        text = content.strip()
        if not text:
            return MemoryUseDecision(False, "empty content", 0.0, [])

        signals = _matched_signals(text, CAPTURE_SIGNALS)
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


class StoreMemoryRetriever:
    def __init__(self, store: MemoryStore):
        self.store = store

    def retrieve(
        self,
        query: str,
        *,
        limit: int,
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


class RuleMemoryReranker:
    def rerank(self, query: str, results: list[SearchResult]) -> list[SearchResult]:
        now = datetime.now(timezone.utc)
        reranked: list[SearchResult] = []
        for result in results:
            memory = result.memory
            relevance = _normalize_relevance(result.score)
            recency = _recency_score(memory.updated_at, now)
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


@dataclass(frozen=True)
class TraitCandidate:
    trait_type: str
    trait_key: str
    statement: str
    scope: str
    evidence_type: str
    evidence_content: str
    confidence: float


class RuleProfileConsolidator:
    def __init__(self, store: MemoryStore, config: ConsolidationConfig | None = None):
        self.store = store
        self.config = config or ConsolidationConfig()

    def consolidate(self, *, recent: int = 100) -> ConsolidationResult:
        memories = self.store.recent_unconsolidated_memories(limit=recent)
        behavior_events = self.store.recent_unconsolidated_behavior_events(limit=recent)

        evidence: list[ProfileEvidence] = []
        updated_traits: list[ProfileTrait] = []
        trait_cache: dict[str, ProfileTrait] = {}

        for memory in memories:
            candidate = self._candidate_from_memory(memory)
            if not candidate:
                continue
            item = self._evidence_from_candidate(candidate, source_memory_id=memory.id, source_event_id=memory.event_id)
            evidence.append(item)
            trait = self._build_trait(candidate, item, existing=trait_cache.get(candidate.trait_key))
            trait_cache[candidate.trait_key] = trait
            updated_traits.append(trait)

        consolidated_behavior_ids: list[str] = []
        for event in behavior_events:
            candidate = self._candidate_from_behavior_event(event)
            if not candidate:
                continue
            item = self._evidence_from_candidate(candidate, behavior_event_id=event.id)
            evidence.append(item)
            trait = self._build_trait(candidate, item, existing=trait_cache.get(candidate.trait_key))
            trait_cache[candidate.trait_key] = trait
            updated_traits.append(trait)
            consolidated_behavior_ids.append(event.id)

        self.store.add_profile_evidence(evidence)
        for trait in trait_cache.values():
            self.store.upsert_profile_trait(trait)
        self.store.mark_behavior_events_consolidated(consolidated_behavior_ids, now_iso())

        return ConsolidationResult(
            evidence_created=evidence,
            traits_updated=self._dedupe_traits(updated_traits),
            memories_scanned=len(memories),
            behavior_events_scanned=len(behavior_events),
        )

    def _candidate_from_memory(self, memory: Memory) -> TraitCandidate | None:
        text = memory.content
        tags = set(memory.tags)
        if memory.type == "preference":
            return TraitCandidate(
                trait_type="preference",
                trait_key="general.preference",
                statement=self._clean_statement(text),
                scope="general",
                evidence_type="explicit_statement",
                evidence_content=text,
                confidence=memory.confidence,
            )

        if memory.type == "style":
            return TraitCandidate(
                trait_type="style",
                trait_key="communication.answer_style",
                statement=self._clean_statement(text),
                scope="communication",
                evidence_type="explicit_statement",
                evidence_content=text,
                confidence=memory.confidence,
            )

        return None

    def _candidate_from_behavior_event(self, event: BehaviorEvent) -> TraitCandidate | None:
        if event.chosen:
            return TraitCandidate(
                trait_type="decision_style",
                trait_key="general.decision_style",
                statement=f"用户在“{event.context}”中选择了 {', '.join(event.chosen)}。",
                scope="general",
                evidence_type="behavior_choice",
                evidence_content=self._behavior_evidence_text(event),
                confidence=0.62,
            )
        return None

    def _evidence_from_candidate(
        self,
        candidate: TraitCandidate,
        *,
        source_event_id: str | None = None,
        source_memory_id: str | None = None,
        behavior_event_id: str | None = None,
    ) -> ProfileEvidence:
        return ProfileEvidence(
            id=new_id("evd"),
            trait_key=candidate.trait_key,
            evidence_type=candidate.evidence_type,
            content=candidate.evidence_content,
            source_event_id=source_event_id,
            source_memory_id=source_memory_id,
            behavior_event_id=behavior_event_id,
            confidence=candidate.confidence,
        )

    def _build_trait(
        self,
        candidate: TraitCandidate,
        evidence: ProfileEvidence,
        *,
        existing: ProfileTrait | None = None,
    ) -> ProfileTrait:
        existing = existing or self.store.get_profile_trait(candidate.trait_key)
        timestamp = now_iso()
        if not existing:
            return ProfileTrait(
                id=new_id("trt"),
                trait_type=candidate.trait_type,
                trait_key=candidate.trait_key,
                statement=candidate.statement,
                scope=candidate.scope,
                stability=0.45,
                confidence=candidate.confidence,
                evidence_count=1,
                evidence_ids=[evidence.id],
                status="active",
                first_seen_at=timestamp,
                last_confirmed_at=timestamp,
                updated_at=timestamp,
            )

        evidence_ids = [*existing.evidence_ids, evidence.id]
        evidence_count = existing.evidence_count + 1
        confidence = min(self.config.max_confidence, max(existing.confidence, candidate.confidence) + 0.04)
        stability = min(self.config.max_stability, existing.stability + self.config.stability_increment)
        return ProfileTrait(
            id=existing.id,
            trait_type=existing.trait_type,
            trait_key=existing.trait_key,
            statement=candidate.statement if len(candidate.statement) >= len(existing.statement) else existing.statement,
            scope=existing.scope,
            stability=stability,
            confidence=confidence,
            evidence_count=evidence_count,
            evidence_ids=evidence_ids[-20:],
            status="active",
            first_seen_at=existing.first_seen_at,
            last_confirmed_at=timestamp,
            updated_at=timestamp,
        )

    def _clean_statement(self, text: str) -> str:
        return text.removeprefix("用户偏好/倾向：").strip()

    def _behavior_evidence_text(self, event: BehaviorEvent) -> str:
        parts = [f"上下文：{event.context}"]
        if event.chosen:
            parts.append(f"选择：{', '.join(event.chosen)}")
        if event.rejected:
            parts.append(f"拒绝：{', '.join(event.rejected)}")
        if event.deferred:
            parts.append(f"推迟：{', '.join(event.deferred)}")
        if event.reason:
            parts.append(f"理由：{event.reason}")
        return "；".join(parts)

    def _dedupe_traits(self, traits: list[ProfileTrait]) -> list[ProfileTrait]:
        by_key: dict[str, ProfileTrait] = {}
        for trait in traits:
            by_key[trait.trait_key] = trait
        return list(by_key.values())


def _matched_signals(text: str, signal_map: dict[str, list[str]]) -> list[str]:
    signals: list[str] = []
    for signal, markers in signal_map.items():
        if any(marker.lower() in text.lower() for marker in markers):
            signals.append(signal)
    return signals


def _normalize_relevance(raw_score: float) -> float:
    if raw_score < 0:
        return min(1.0, abs(raw_score) * 100000)
    return max(0.0, min(1.0, raw_score))


def _recency_score(updated_at: str, now: datetime) -> float:
    try:
        updated = datetime.fromisoformat(updated_at)
    except ValueError:
        return 0.3
    age_days = max(0.0, (now - updated).total_seconds() / 86400)
    return math.exp(-age_days / 30)
