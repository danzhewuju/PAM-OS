from __future__ import annotations

import math
import re
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
    QueryIntent,
    SearchResult,
    new_id,
    now_iso,
)
from pam_os.store import MemoryStore


READ_SIGNALS = {
    "personal_reference": [
        "我",
        "我的",
        "偏好",
        "风格",
        "目标",
        "长期",
        "之前",
        "上次",
        "继续",
        "记得",
        "my",
        "mine",
        "my preference",
        "my preferences",
        "my style",
        "my goal",
        "long-term",
        "previously",
        "last time",
        "continue",
        "remember",
    ],
    "project_reference": [
        "项目",
        "当前项目",
        "当前阶段",
        "project",
        "current project",
        "repo",
        "repository",
        "current repo",
        "this repo",
        "this project",
        "codebase",
        "current codebase",
    ],
    "preference_reference": [
        "喜欢",
        "不喜欢",
        "倾向",
        "符合我",
        "按我的",
        "不要",
        "希望",
        "prefer",
        "preference",
        "preferred",
        "usual style",
        "according to my",
        "as I like",
        "do not want",
        "don't want",
    ],
    "history_reference": [
        "之前说过",
        "历史",
        "决策",
        "背景",
        "上下文",
        "继续做",
        "as we discussed",
        "as mentioned before",
        "previous decision",
        "context",
        "background",
        "continue where we left off",
        "pick up where we left off",
        "where we left off",
    ],
    "identity_reference": [
        "我是谁",
        "你知道我是谁",
        "我的名字",
        "我叫什么",
        "我叫啥",
        "姓名",
        "身份",
        "who am i",
        "who i am",
        "my name",
        "what am i called",
        "what is my name",
        "do you know my name",
        "do you remember my name",
        "identity",
    ],
    "task_work_reference": [
        "pamr",
        "帮我排查",
        "排查一下",
        "帮我分析",
        "分析一下",
        "解决一下",
        "帮我解决",
        "优化一下",
        "帮我优化",
        "修复一下",
        "帮我修复",
        "实现一下",
        "帮我实现",
        "这个项目",
        "当前仓库",
        "这个仓库",
        "this repo",
        "this project",
        "troubleshoot",
        "troubleshooting",
        "debug",
        "debugging",
        "analyze",
        "analyzing",
        "analyse",
        "analysing",
        "solve",
        "solving",
        "fix",
        "fixing",
        "optimize",
        "optimizing",
        "optimise",
        "optimising",
        "implement",
        "implementing",
        "help me troubleshoot",
        "help me debug",
        "help me analyze",
        "help me analyse",
        "help me solve",
        "help me fix",
        "help me optimize",
        "help me optimise",
        "help me implement",
    ],
}

CAPTURE_SIGNALS = {
    "identity": [
        "我是",
        "我叫",
        "用户叫",
        "用户姓名是",
        "用户身份信息",
        "我的名字是",
        "我的姓名是",
        "my name is",
        "i am called",
        "i'm called",
        "hello i am",
        "hello i'm",
        "hello, i am",
        "hello, i'm",
        "hi i am",
        "hi i'm",
        "hi, i am",
        "hi, i'm",
        "hey i am",
        "hey i'm",
        "hey, i am",
        "hey, i'm",
    ],
    "preference": [
        "我偏好",
        "我喜欢",
        "我不喜欢",
        "我倾向",
        "更希望",
        "不要一开始",
        "自动一点",
        "不想要",
        "i prefer",
        "i like",
        "i don't like",
        "i do not like",
        "i tend to",
        "i'd rather",
        "i would rather",
        "i don't want",
        "i do not want",
        "i want you to remember",
        "remember that",
    ],
    "goal": [
        "我的目标",
        "我希望",
        "下一步",
        "计划",
        "准备做",
        "接下来要",
        "my goal",
        "i plan to",
        "my plan is",
        "next step",
        "next i will",
        "i'm going to",
        "i am going to",
    ],
    "project": [
        "项目",
        "决定",
        "当前项目",
        "当前阶段",
        "先用",
        "不引入",
        "我们先",
        "保持这种",
        "这个方向",
        "we decided",
        "i decided",
        "decision",
        "we will use",
        "we should use",
        "i will use",
        "i should use",
        "don't introduce",
        "do not introduce",
        "not introduce",
        "keep this direction",
        "current phase",
    ],
    "style": [
        "回答风格",
        "以后回答",
        "以后就",
        "就这么",
        "直接",
        "工程化",
        "少营销",
        "别这么",
        "answer style",
        "next time",
        "in the future",
        "from now on",
        "keep doing this",
        "be direct",
        "more direct",
        "engineering-focused",
        "engineering focused",
        "less marketing",
        "don't start with",
        "do not start with",
        "default to",
    ],
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
        normalized = text.lower()
        if any(_contains_marker(normalized, marker) for marker in ["我", "我的", "my", "mine"]):
            confidence += 0.1
        if any(
            _contains_marker(normalized, marker)
            for marker in [
                "继续",
                "之前",
                "continue",
                "previously",
                "last time",
                "where we left off",
            ]
        ):
            confidence += 0.12
        if "task_work_reference" in signals:
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
        normalized = text.lower()
        if any(
            _contains_marker(normalized, marker)
            for marker in [
                "决定",
                "偏好",
                "喜欢",
                "名字",
                "我叫",
                "目标",
                "不引入",
                "先用",
                "以后",
                "保持",
                "自动",
                "decided",
                "decision",
                "prefer",
                "goal",
                "do not introduce",
                "don't introduce",
                "first",
                "future",
                "keep",
                "default",
            ]
        ):
            confidence += 0.15
        confidence = min(confidence, 0.95)

        if confidence >= self.config.capture_threshold:
            return MemoryUseDecision(True, "content contains stable user/project information", confidence, signals)
        return MemoryUseDecision(False, "content looks transient", max(confidence, 0.3), signals)


class RuleQueryIntentClassifier:
    def classify(self, query: str, conversation_summary: str | None = None) -> QueryIntent:
        text = f"{query}\n{conversation_summary or ''}".strip()
        if not text:
            return QueryIntent(False, "empty query", 0.0)

        memory_types: list[str] = []
        trait_keys: list[str] = []
        signals: list[str] = []
        if _matches_any(
            text,
            [
                "我是谁",
                "你知道我是谁",
                "我的名字",
                "我叫什么",
                "我叫啥",
                "姓名",
                "身份",
                r"\bwho am i\b",
                r"\bwho i am\b",
                r"\bmy name\b",
                r"\bwhat am i called\b",
                r"\bwhat is my name\b",
                r"\bdo you know my name\b",
                r"\bdo you remember my name\b",
            ],
        ):
            memory_types.extend(["identity", "preference"])
            trait_keys.extend(["profile.identity.", "general.preference", "preference."])
            signals.append("intent:identity")

        if _matches_any(
            text,
            [
                "我喜欢什么",
                "我的喜好",
                "我的兴趣",
                "我偏好什么",
                r"\bwhat do i like\b",
                r"\bwhat i like\b",
                r"\bwhat are my interests\b",
                r"\bmy interests\b",
                r"\bmy preferences\b",
                r"\bwhat do i prefer\b",
            ],
        ):
            memory_types.append("preference")
            trait_keys.extend(["general.preference", "preference."])
            signals.append("intent:preference")

        if _matches_any(text, ["回答风格", "我的风格", r"\bmy style\b", r"\busual style\b"]):
            memory_types.append("style")
            trait_keys.append("communication.answer_style")
            signals.append("intent:style")

        if _matches_any(text, ["当前项目", "这个项目", "项目背景", r"\bthis project\b", r"\bcurrent project\b"]):
            memory_types.append("project")
            trait_keys.append("project.")
            signals.append("intent:project")

        memory_types = _dedupe_strings(memory_types)
        trait_keys = _dedupe_strings(trait_keys)
        if not memory_types and not trait_keys:
            return QueryIntent(False, "no namespace query intent", 0.0)
        confidence = min(0.92, 0.58 + 0.08 * len(signals))
        return QueryIntent(
            True,
            "query intent indicates memory namespace",
            confidence,
            memory_types=memory_types,
            trait_keys=trait_keys,
            signals=signals,
        )


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
            stability = 0.85 if memory.type in {"identity", "preference", "goal", "project", "style"} else 0.45
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
        fact_key = self._fact_key_from_memory(memory)
        if memory.type == "identity":
            return self._trait_candidate(
                memory,
                trait_type="identity",
                trait_key=fact_key or "profile.identity.name",
                scope="profile",
            )

        if memory.type == "preference":
            trait_key = fact_key or "general.preference"
            scope = "preferences" if trait_key.startswith("preference.") else "general"
            return self._trait_candidate(memory, trait_type="preference", trait_key=trait_key, scope=scope)

        if memory.type == "style":
            return self._trait_candidate(
                memory,
                trait_type="style",
                trait_key=fact_key or "communication.answer_style",
                scope="communication",
            )

        if memory.type == "goal":
            return self._trait_candidate(
                memory,
                trait_type="goal",
                trait_key=fact_key or "long_term.goal",
                scope="goals",
            )

        if memory.type == "project":
            trait_key = fact_key or "project.active_context"
            return self._trait_candidate(memory, trait_type="project", trait_key=trait_key, scope="project")

        return None

    def _trait_candidate(
        self,
        memory: Memory,
        *,
        trait_type: str,
        trait_key: str,
        scope: str,
    ) -> TraitCandidate:
        return TraitCandidate(
            trait_type=trait_type,
            trait_key=trait_key,
            statement=self._clean_statement(memory.content),
            scope=scope,
            evidence_type="explicit_statement",
            evidence_content=memory.content,
            confidence=memory.confidence,
        )

    def _fact_key_from_memory(self, memory: Memory) -> str | None:
        for tag in memory.tags:
            if tag.startswith("fact:"):
                key = tag.removeprefix("fact:").strip()
                return key or None
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
        statement = text.strip()
        for prefix in ["用户身份信息：", "用户偏好/倾向：", "用户目标/计划：", "用户项目上下文："]:
            statement = statement.removeprefix(prefix)
        return statement.strip()

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


def _matches_any(text: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if pattern.startswith("\\b") or "(?:" in pattern or "\\s" in pattern:
            try:
                if re.search(pattern, text, flags=re.IGNORECASE):
                    return True
            except re.error:
                continue
        elif _contains_marker(text.lower(), pattern):
            return True
    return False


def _dedupe_strings(items: list[str]) -> list[str]:
    return [item for index, item in enumerate(items) if item and item not in items[:index]]


def _matched_signals(text: str, signal_map: dict[str, list[str]]) -> list[str]:
    signals: list[str] = []
    normalized = text.lower()
    for signal, markers in signal_map.items():
        if any(_contains_marker(normalized, marker) for marker in markers):
            signals.append(signal)
    return signals


def _contains_marker(normalized_text: str, marker: str) -> bool:
    normalized_marker = marker.lower()
    if _is_ascii_marker(normalized_marker):
        return re.search(rf"(?<![A-Za-z0-9_]){re.escape(normalized_marker)}(?![A-Za-z0-9_])", normalized_text) is not None
    return normalized_marker in normalized_text


def _is_ascii_marker(marker: str) -> bool:
    return bool(re.search(r"[a-z0-9]", marker)) and marker.isascii()


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
