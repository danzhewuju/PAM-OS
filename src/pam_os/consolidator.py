from __future__ import annotations

from dataclasses import dataclass

from pam_os.config import ConsolidationConfig
from pam_os.models import (
    BehaviorEvent,
    ConsolidationResult,
    Memory,
    ProfileEvidence,
    ProfileTrait,
    new_id,
    now_iso,
)
from pam_os.store import MemoryStore


@dataclass(frozen=True)
class TraitCandidate:
    trait_type: str
    trait_key: str
    statement: str
    scope: str
    evidence_type: str
    evidence_content: str
    confidence: float


class MemoryConsolidator:
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
        if memory.type == "preference" or "self-host" in tags or "control" in tags:
            if any(marker in text.lower() for marker in ["self-host", "本地", "可控", "开源", "cloud", "saas"]):
                return TraitCandidate(
                    trait_type="preference",
                    trait_key="deployment.control",
                    statement="用户长期偏好 self-host、开源、本地可控的系统。",
                    scope="technical",
                    evidence_type="explicit_statement",
                    evidence_content=text,
                    confidence=max(memory.confidence, 0.7),
                )
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
                statement="用户偏好直接、工程化、可执行的回答风格。",
                scope="communication",
                evidence_type="explicit_statement",
                evidence_content=text,
                confidence=max(memory.confidence, 0.68),
            )

        if memory.type in {"project", "goal"} and any(
            marker in text for marker in ["先用", "不引入", "轻量", "MVP", "SQLite", "Qdrant", "重型"]
        ):
            return TraitCandidate(
                trait_type="decision_style",
                trait_key="technical.decision_style",
                statement="用户做技术决策时倾向先选择轻量、本地、可控、可运行的方案验证闭环，再逐步引入复杂基础设施。",
                scope="technical",
                evidence_type="repeated_pattern",
                evidence_content=text,
                confidence=max(memory.confidence, 0.66),
            )

        return None

    def _candidate_from_behavior_event(self, event: BehaviorEvent) -> TraitCandidate | None:
        combined = " ".join(event.chosen + event.rejected + event.deferred + [event.reason or "", event.context])
        if any(marker in combined for marker in ["SQLite", "FTS5", "本地", "轻量", "可控"]) and any(
            marker in combined for marker in ["Qdrant", "Neo4j", "Flink", "Kafka", "重型"]
        ):
            return TraitCandidate(
                trait_type="decision_style",
                trait_key="technical.decision_style",
                statement="用户做技术决策时倾向先选择轻量、本地、可控、可运行的方案验证闭环，再逐步引入复杂基础设施。",
                scope="technical",
                evidence_type="behavior_choice",
                evidence_content=self._behavior_evidence_text(event),
                confidence=0.78,
            )
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
