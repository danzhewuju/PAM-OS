from __future__ import annotations

import re
from typing import Any

from pam_os.config import OrchestratorConfig
from pam_os.models import MemoryUseDecision, PolicySignal, new_id, now_iso
from pam_os.providers import MemoryPolicy
from pam_os.rule_provider import RuleMemoryPolicy
from pam_os.store import MemoryStore


class AdaptiveMemoryPolicy:
    def __init__(
        self,
        store: MemoryStore,
        *,
        seed_policy: MemoryPolicy | None = None,
        config: OrchestratorConfig | None = None,
        learned_margin: float = 0.08,
    ):
        self.store = store
        self.seed_policy = seed_policy or RuleMemoryPolicy(config)
        self.learned_margin = learned_margin

    def decide_read(self, task: str, conversation_summary: str | None = None) -> MemoryUseDecision:
        text = f"{task}\n{conversation_summary or ''}".strip()
        learned = self._decision_from_learned_signals(text, signal_type="read", action="use_memory")
        seed = self.seed_policy.decide_read(task, conversation_summary)
        return self._merge_decisions(learned, seed)

    def decide_capture(self, content: str, metadata: dict[str, Any] | None = None) -> MemoryUseDecision:
        learned = self._decision_from_learned_signals(content, signal_type="capture", action="capture_memory")
        seed = self.seed_policy.decide_capture(content, metadata)
        return self._merge_decisions(learned, seed)

    def _decision_from_learned_signals(
        self,
        text: str,
        *,
        signal_type: str,
        action: str,
    ) -> MemoryUseDecision | None:
        if not text.strip():
            return None
        matches: list[PolicySignal] = []
        for signal in self.store.list_policy_signals(
            signal_type=signal_type,
            action=action,
            statuses=["active", "stable"],
            limit=100,
        ):
            if _pattern_matches(signal.pattern, text):
                matches.append(signal)
        if not matches:
            return None

        score = min(0.98, max(signal.confidence for signal in matches) + self.learned_margin)
        signals = [f"learned:{signal.normalized_intent}" for signal in matches[:5]]
        reason = "learned policy signal matched"
        return MemoryUseDecision(True, reason, score, signals)

    def _merge_decisions(
        self,
        learned: MemoryUseDecision | None,
        seed: MemoryUseDecision,
    ) -> MemoryUseDecision:
        if learned and (learned.should_use or learned.confidence >= seed.confidence):
            return learned
        return seed


class PolicySignalLearner:
    def __init__(self, store: MemoryStore):
        self.store = store

    def learn_signal(
        self,
        *,
        signal_type: str,
        pattern: str,
        normalized_intent: str,
        action: str,
        scope: str = "general",
        confidence: float = 0.66,
        source: str = "user_feedback",
        status: str | None = None,
    ) -> PolicySignal:
        existing = self.store.get_policy_signal(signal_type, pattern, action)
        if existing:
            supported = True
            return self.store.reinforce_policy_signal(
                signal_type=signal_type,
                pattern=pattern,
                action=action,
                supported=supported,
                confidence_delta=max(0.02, confidence - existing.confidence),
            ) or existing

        confidence = max(0.0, min(0.98, confidence))
        signal = PolicySignal(
            id=new_id("psg"),
            signal_type=signal_type,
            scope=scope,
            pattern=pattern.strip(),
            normalized_intent=normalized_intent.strip(),
            action=action,
            confidence=confidence,
            support_count=1,
            reject_count=0,
            source=source,
            status=status or _initial_status(confidence),
            created_at=now_iso(),
            updated_at=now_iso(),
        )
        self.store.upsert_policy_signal(signal)
        return signal

    def reinforce_signal(
        self,
        *,
        signal_type: str,
        pattern: str,
        action: str,
        supported: bool,
    ) -> PolicySignal | None:
        return self.store.reinforce_policy_signal(
            signal_type=signal_type,
            pattern=pattern,
            action=action,
            supported=supported,
        )


def _pattern_matches(pattern: str, text: str) -> bool:
    pattern = pattern.strip()
    if not pattern:
        return False
    if pattern.startswith("regex:"):
        expression = pattern.removeprefix("regex:").strip()
        try:
            return re.search(expression, text, flags=re.IGNORECASE) is not None
        except re.error:
            return False
    return pattern.lower() in text.lower()


def _initial_status(confidence: float) -> str:
    if confidence >= 0.85:
        return "stable"
    if confidence >= 0.62:
        return "active"
    return "candidate"
