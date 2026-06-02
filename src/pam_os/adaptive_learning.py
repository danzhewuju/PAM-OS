from __future__ import annotations

import re
from dataclasses import dataclass, field

from pam_os.adaptive_policy import TextPolicyFeatureExtractor
from pam_os.models import CaptureResult, PolicySignal


@dataclass(frozen=True)
class PolicySignalCandidate:
    signal_type: str
    pattern: str
    normalized_intent: str
    action: str
    scope: str = "general"
    source_text: str = ""
    signals: list[str] = field(default_factory=list)
    source: str = "auto_observer"


@dataclass(frozen=True)
class AdmissionDecision:
    allow: bool
    status: str
    confidence: float
    reason: str
    signals: list[str] = field(default_factory=list)
    risk: str = "low"


@dataclass(frozen=True)
class PolicyLearningOutcome:
    candidate: PolicySignalCandidate
    decision: AdmissionDecision
    signal: PolicySignal | None = None


@dataclass(frozen=True)
class ObservedTurnResult:
    memory_captures: list[CaptureResult] = field(default_factory=list)
    policy_outcomes: list[PolicyLearningOutcome] = field(default_factory=list)


class AdaptiveLearningLoop:
    def __init__(
        self,
        *,
        feature_extractor: TextPolicyFeatureExtractor | None = None,
        admission_controller: "PolicySignalAdmissionController | None" = None,
    ):
        self.feature_extractor = feature_extractor or TextPolicyFeatureExtractor()
        self.admission_controller = admission_controller or PolicySignalAdmissionController()

    def policy_candidates(
        self,
        *,
        user_message: str,
        assistant_message: str = "",
        conversation_summary: str | None = None,
    ) -> list[PolicySignalCandidate]:
        text = user_message.strip()
        if not text:
            return []

        read_features = self.feature_extractor.extract_read(text, conversation_summary)
        capture_features = self.feature_extractor.extract_capture(text)
        candidates: list[PolicySignalCandidate] = []

        if capture_features.has("future_instruction"):
            candidates.append(
                PolicySignalCandidate(
                    signal_type="capture",
                    pattern="feature:future_instruction",
                    normalized_intent="durable_future_instruction",
                    action="capture_memory",
                    scope="workflow",
                    source_text=text,
                    signals=sorted(capture_features.names),
                )
            )

        if capture_features.has("explicit_memory_intent"):
            candidates.append(
                PolicySignalCandidate(
                    signal_type="capture",
                    pattern="feature:explicit_memory_intent",
                    normalized_intent="explicit_memory_request",
                    action="capture_memory",
                    scope="workflow",
                    source_text=text,
                    signals=sorted(capture_features.names),
                )
            )

        if read_features.has("short_followup"):
            candidates.append(
                PolicySignalCandidate(
                    signal_type="read",
                    pattern="feature:short_followup",
                    normalized_intent="short_followup_continuation",
                    action="use_memory",
                    scope="workflow",
                    source_text=text,
                    signals=sorted(read_features.names),
                )
            )

        if read_features.has("continuity_reference") and read_features.has("project_context_reference"):
            candidates.append(
                PolicySignalCandidate(
                    signal_type="read",
                    pattern="feature:continuity_reference",
                    normalized_intent="continue_project_or_thread",
                    action="use_memory",
                    scope="project",
                    source_text=text,
                    signals=sorted(read_features.names),
                )
            )

        if self._looks_like_negative_feedback(text):
            candidates.append(
                PolicySignalCandidate(
                    signal_type="read",
                    pattern="feature:short_followup",
                    normalized_intent="reject_wrong_context",
                    action="use_memory",
                    scope="workflow",
                    source_text=text,
                    signals=["correction_feedback"],
                )
            )

        return self._dedupe_candidates(candidates)

    def admission_for(self, candidate: PolicySignalCandidate) -> AdmissionDecision:
        return self.admission_controller.evaluate(candidate)

    def _looks_like_negative_feedback(self, text: str) -> bool:
        lower = text.lower()
        return any(token in text for token in ["不是这个", "不是那个", "你记错", "别读这个"]) or any(
            token in lower for token in ["not that", "wrong context", "wrong memory", "don't use that memory"]
        )

    def _dedupe_candidates(self, candidates: list[PolicySignalCandidate]) -> list[PolicySignalCandidate]:
        seen: set[tuple[str, str, str]] = set()
        deduped: list[PolicySignalCandidate] = []
        for candidate in candidates:
            key = (candidate.signal_type, candidate.pattern, candidate.action)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped


class PolicySignalAdmissionController:
    def evaluate(self, candidate: PolicySignalCandidate) -> AdmissionDecision:
        text = candidate.source_text
        risk = self._risk_for(candidate, text)
        if risk == "high":
            return AdmissionDecision(
                False,
                "skipped",
                0.0,
                "high-risk or overly broad automatic learning candidate",
                candidate.signals,
                risk,
            )

        score = 0.2
        signals = set(candidate.signals)
        if "future_instruction" in signals:
            score += 0.35
        if "explicit_memory_intent" in signals:
            score += 0.25
        if "first_person" in signals:
            score += 0.1
        if "short_followup" in signals:
            score += 0.25
        if "continuity_reference" in signals:
            score += 0.1
        if "project_context_reference" in signals:
            score += 0.1
        if "correction_feedback" in signals:
            score += 0.2
        if self._contains_durable_words(text):
            score += 0.15
        if self._looks_model_only(candidate):
            score -= 0.2
        if self._pattern_too_broad(candidate):
            score -= 0.3

        confidence = max(0.0, min(0.98, score))
        if confidence >= 0.62:
            return AdmissionDecision(
                True,
                "active",
                confidence,
                "local admission score passed active threshold",
                sorted(signals),
                risk,
            )
        if confidence >= 0.4:
            return AdmissionDecision(
                True,
                "candidate",
                confidence,
                "local admission score passed candidate threshold",
                sorted(signals),
                risk,
            )
        return AdmissionDecision(
            False,
            "skipped",
            confidence,
            "local admission score below candidate threshold",
            sorted(signals),
            risk,
        )

    def risk_for_text(self, text: str) -> str:
        lower = text.lower()
        high_risk_tokens = [
            "password",
            "secret",
            "token",
            "api key",
            "credential",
            "记住所有",
            "永远读记忆",
            "所有问题都读记忆",
            "remember everything",
            "always use memory",
            "never ask before saving",
        ]
        if any(token in lower or token in text for token in high_risk_tokens):
            return "high"
        medium_tokens = ["身份", "职业", "医生", "律师", "财务", "medical", "legal", "financial"]
        if any(token in lower or token in text for token in medium_tokens):
            return "medium"
        return "low"

    def _risk_for(self, candidate: PolicySignalCandidate, text: str) -> str:
        return self.risk_for_text(text)

    def _contains_durable_words(self, text: str) -> bool:
        lower = text.lower()
        return any(token in text for token in ["以后", "下次", "默认", "保持这种"]) or any(
            token in lower for token in ["from now on", "next time", "default to", "keep doing this"]
        )

    def _looks_model_only(self, candidate: PolicySignalCandidate) -> bool:
        return candidate.source == "model_inference"

    def _pattern_too_broad(self, candidate: PolicySignalCandidate) -> bool:
        pattern = candidate.pattern.lower()
        return pattern in {"memory", "remember", "feature:first_person"} or re.fullmatch(r"\w{1,3}", pattern) is not None
