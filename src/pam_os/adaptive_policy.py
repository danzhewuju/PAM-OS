from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from pam_os.config import OrchestratorConfig
from pam_os.models import MemoryUseDecision, PolicySignal, new_id, now_iso
from pam_os.providers import MemoryPolicy
from pam_os.rule_provider import RuleMemoryPolicy
from pam_os.store import MemoryStore


@dataclass
class PolicyFeatures:
    text: str
    names: set[str] = field(default_factory=set)

    def has(self, name: str) -> bool:
        return name in self.names


class TextPolicyFeatureExtractor:
    def extract_read(self, task: str, conversation_summary: str | None = None) -> PolicyFeatures:
        text = f"{task}\n{conversation_summary or ''}".strip()
        features = self._extract_common(text)
        self._add_matches(
            features,
            text,
            {
                "explicit_read_request": [r"\bpamr\b", "读一下记忆", "读取记忆"],
                "continuity_reference": [
                    "继续",
                    "之前",
                    "上次",
                    "刚才",
                    r"\bcontinue\b",
                    r"\bprevious(?:ly)?\b",
                    r"\bearlier\b",
                    r"\blast time\b",
                    r"\bwhere we left off\b",
                    r"\bpick up where we left off\b",
                    r"\bas we discussed\b",
                    r"\bas mentioned before\b",
                ],
                "short_followup": [
                    "那条线",
                    "那个方向",
                    "同一个",
                    r"\bthat one\b",
                    r"\bsame one\b",
                    r"\bthat thread\b",
                    r"\bthat direction\b",
                    r"\bsame approach\b",
                ],
                "preference_reference": [
                    "按我的",
                    "符合我",
                    "偏好",
                    "风格",
                    r"\bmy preference\b",
                    r"\bmy preferences\b",
                    r"\bmy style\b",
                    r"\busual style\b",
                    r"\baccording to my\b",
                    r"\bpreferred\b",
                ],
                "project_context_reference": [
                    "这个项目",
                    "当前项目",
                    "这个仓库",
                    "当前仓库",
                    r"\bthis project\b",
                    r"\bcurrent project\b",
                    r"\bthis repo\b",
                    r"\bcurrent repo\b",
                    r"\brepository\b",
                    r"\bcodebase\b",
                ],
                "task_work_intent": [
                    "排查",
                    "分析",
                    "解决",
                    "优化",
                    "修复",
                    "实现",
                    r"\btroubleshoot(?:ing)?\b",
                    r"\bdebug(?:ging)?\b",
                    r"\banaly[sz]e\b",
                    r"\bsolv(?:e|ing)\b",
                    r"\bfix(?:ing)?\b",
                    r"\boptimi[sz](?:e|ing)\b",
                    r"\bimplement(?:ing)?\b",
                ],
                "memory_reference": [
                    "记得",
                    "记忆",
                    r"\bremember what\b",
                    r"\bwhat I said\b",
                    r"\bfrom memory\b",
                ],
                "identity_reference": [
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
                    r"\bidentity\b",
                ],
            },
        )
        if self._looks_generic_question(text) and not features.names - {"question", "generic_question"}:
            features.names.add("generic_question")
        return PolicyFeatures(text=text, names=features.names)

    def extract_capture(self, content: str, metadata: dict[str, Any] | None = None) -> PolicyFeatures:
        text = content.strip()
        metadata = metadata or {}
        features = self._extract_common(text)
        self._add_matches(
            features,
            text,
            {
                "explicit_memory_intent": [
                    r"\bpamw\b",
                    "记住",
                    "记一下",
                    r"\bremember this\b",
                    r"\bremember that\b",
                    r"\bi want you to remember\b",
                ],
                "identity_statement": [
                    "我是",
                    "我叫",
                    "用户叫",
                    "用户姓名是",
                    "用户身份信息",
                    "我的名字是",
                    "我的姓名是",
                    r"\bmy name is\b",
                    r"\bi am called\b",
                    r"\bi'm called\b",
                    r"\b(?:hello|hi|hey),?\s+i am [A-Za-z][A-Za-z0-9_-]{1,31}\b",
                    r"\b(?:hello|hi|hey),?\s+i'm [A-Za-z][A-Za-z0-9_-]{1,31}\b",
                ],
                "preference_statement": [
                    "我偏好",
                    "我喜欢",
                    "我不喜欢",
                    "我倾向",
                    r"\bi prefer\b",
                    r"\bi like\b",
                    r"\bi do(?:n't| not) like\b",
                    r"\bi tend to\b",
                    r"\bi(?:'d| would) rather\b",
                ],
                "goal_statement": [
                    "我的目标",
                    "我希望",
                    "计划",
                    "接下来要",
                    r"\bmy goal\b",
                    r"\bi plan to\b",
                    r"\bmy plan is\b",
                    r"\bnext step\b",
                    r"\bi(?:'m| am) going to\b",
                ],
                "decision_statement": [
                    "决定",
                    "先用",
                    "不引入",
                    "我们先",
                    r"\bwe decided\b",
                    r"\bi decided\b",
                    r"\bdecision\b",
                    r"\bwe (?:will|should) use\b",
                    r"\bi (?:will|should) use\b",
                    r"\bdo(?:n't| not) introduce\b",
                    r"\bnot introduce\b",
                ],
                "future_instruction": [
                    "以后",
                    "下次",
                    "默认",
                    "保持这种",
                    r"\bnext time\b",
                    r"\bin the future\b",
                    r"\bfrom now on\b",
                    r"\bdefault to\b",
                    r"\bkeep doing this\b",
                ],
                "style_instruction": [
                    "回答风格",
                    "直接",
                    "工程化",
                    "少营销",
                    r"\banswer style\b",
                    r"\bbe direct\b",
                    r"\bmore direct\b",
                    r"\bengineering[- ]focused\b",
                    r"\bless marketing\b",
                ],
                "correction_statement": [
                    "不是我的偏好",
                    "别这么",
                    "不要这样",
                    r"\bnot my preference\b",
                    r"\bi do(?:n't| not) want that\b",
                    r"\bdon(?:'t| not) do that\b",
                ],
            },
        )
        if metadata.get("explicit_memory") is True:
            features.names.add("explicit_memory_intent")
        if self._looks_transient(text):
            features.names.add("transient_chat")
        return PolicyFeatures(text=text, names=features.names)

    def _extract_common(self, text: str) -> PolicyFeatures:
        features = PolicyFeatures(text=text)
        self._add_matches(
            features,
            text,
            {
                "first_person": ["我", "我的", r"\bI\b", r"\bmy\b", r"\bmine\b"],
                "question": [r"\?", "？", "怎么", "如何", r"\bhow\b", r"\bwhat\b", r"\bwhy\b"],
            },
        )
        return features

    def _add_matches(self, features: PolicyFeatures, text: str, patterns: dict[str, list[str]]) -> None:
        for name, candidates in patterns.items():
            if any(_pattern_matches(candidate, text) for candidate in candidates):
                features.names.add(name)

    def _looks_generic_question(self, text: str) -> bool:
        return any(
            _pattern_matches(pattern, text)
            for pattern in [
                "怎么排序",
                "是什么",
                "解释一下",
                "语法",
                "天气",
                "新闻",
                r"\bwhat is\b",
                r"\bhow do I\b",
                r"\bsyntax\b",
                r"\bweather\b",
                r"\bnews\b",
            ]
        )

    def _looks_transient(self, text: str) -> bool:
        normalized = text.strip().lower()
        return normalized in {"ok", "okay", "thanks", "thank you", "哈哈好的", "好的", "收到"}


class AdaptiveMemoryPolicy:
    def __init__(
        self,
        store: MemoryStore,
        *,
        seed_policy: MemoryPolicy | None = None,
        config: OrchestratorConfig | None = None,
        learned_margin: float = 0.08,
        feature_extractor: TextPolicyFeatureExtractor | None = None,
    ):
        self.store = store
        self.seed_policy = seed_policy or RuleMemoryPolicy(config)
        self.config = config or OrchestratorConfig()
        self.learned_margin = learned_margin
        self.feature_extractor = feature_extractor or TextPolicyFeatureExtractor()

    def decide_read(self, task: str, conversation_summary: str | None = None) -> MemoryUseDecision:
        features = self.feature_extractor.extract_read(task, conversation_summary)
        learned = self._decision_from_learned_signals(features, signal_type="read", action="use_memory")
        feature = self._decision_from_read_features(features)
        seed = self.seed_policy.decide_read(task, conversation_summary)
        return self._merge_decisions(learned, feature, seed)

    def decide_capture(self, content: str, metadata: dict[str, Any] | None = None) -> MemoryUseDecision:
        features = self.feature_extractor.extract_capture(content, metadata)
        learned = self._decision_from_learned_signals(features, signal_type="capture", action="capture_memory")
        feature = self._decision_from_capture_features(features)
        seed = self.seed_policy.decide_capture(content, metadata)
        return self._merge_decisions(learned, feature, seed)

    def _decision_from_learned_signals(
        self,
        features: PolicyFeatures,
        *,
        signal_type: str,
        action: str,
    ) -> MemoryUseDecision | None:
        if not features.text.strip():
            return None
        matches: list[PolicySignal] = []
        for signal in self.store.list_policy_signals(
            signal_type=signal_type,
            action=action,
            statuses=["active", "stable"],
            limit=100,
        ):
            if _signal_matches(signal, features):
                matches.append(signal)
        if not matches:
            return None

        score = min(0.98, max(signal.confidence for signal in matches) + self.learned_margin)
        signals = [f"learned:{signal.normalized_intent}" for signal in matches[:5]]
        reason = "learned policy signal matched"
        return MemoryUseDecision(True, reason, score, signals)

    def _decision_from_read_features(self, features: PolicyFeatures) -> MemoryUseDecision:
        if not features.text:
            return MemoryUseDecision(False, "empty task", 0.0, [])
        if features.has("generic_question") and not features.names - {"question", "generic_question"}:
            return MemoryUseDecision(False, "generic factual or one-off question", 0.72, sorted(features.names))

        weights = {
            "explicit_read_request": 0.65,
            "continuity_reference": 0.28,
            "preference_reference": 0.28,
            "project_context_reference": 0.22,
            "task_work_intent": 0.28,
            "memory_reference": 0.24,
            "identity_reference": 0.42,
            "first_person": 0.08,
        }
        score = 0.24 + sum(weights.get(name, 0.0) for name in features.names)
        confidence = min(0.95, score)
        if confidence >= self.config.memory_use_threshold:
            return MemoryUseDecision(
                True,
                "adaptive feature signals indicate memory-dependent task",
                confidence,
                sorted(features.names),
            )
        return MemoryUseDecision(False, "no strong adaptive memory-use signal", max(confidence, 0.3), sorted(features.names))

    def _decision_from_capture_features(self, features: PolicyFeatures) -> MemoryUseDecision:
        if not features.text:
            return MemoryUseDecision(False, "empty content", 0.0, [])
        if features.has("transient_chat"):
            return MemoryUseDecision(False, "content looks transient", 0.72, sorted(features.names))

        weights = {
            "explicit_memory_intent": 0.65,
            "identity_statement": 0.38,
            "preference_statement": 0.32,
            "goal_statement": 0.28,
            "decision_statement": 0.34,
            "future_instruction": 0.32,
            "style_instruction": 0.30,
            "correction_statement": 0.34,
            "first_person": 0.06,
        }
        score = 0.18 + sum(weights.get(name, 0.0) for name in features.names)
        confidence = min(0.95, score)
        if confidence >= self.config.capture_threshold:
            return MemoryUseDecision(
                True,
                "adaptive feature signals indicate stable memory",
                confidence,
                sorted(features.names),
            )
        return MemoryUseDecision(False, "content lacks stable adaptive memory signals", max(confidence, 0.3), sorted(features.names))

    def _merge_decisions(
        self,
        learned: MemoryUseDecision | None,
        feature: MemoryUseDecision,
        seed: MemoryUseDecision,
    ) -> MemoryUseDecision:
        if learned and (learned.should_use or learned.confidence >= seed.confidence):
            return learned
        return max([feature, seed], key=lambda item: item.confidence)


class PolicySignalLearner:
    def __init__(self, store: MemoryStore, feature_extractor: TextPolicyFeatureExtractor | None = None):
        self.store = store
        self.feature_extractor = feature_extractor or TextPolicyFeatureExtractor()

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

    def learn_from_text(
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
    ) -> PolicySignal:
        features = (
            self.feature_extractor.extract_read(text)
            if signal_type == "read"
            else self.feature_extractor.extract_capture(text, metadata)
        )
        pattern = _best_feature_pattern(signal_type, features) or text.strip()
        return self.learn_signal(
            signal_type=signal_type,
            pattern=pattern,
            normalized_intent=normalized_intent,
            action=action,
            scope=scope,
            confidence=confidence,
            source=source,
        )

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
    if pattern.startswith("regex:") or _looks_like_regex(pattern):
        expression = pattern.removeprefix("regex:").strip()
        try:
            return re.search(expression, text, flags=re.IGNORECASE) is not None
        except re.error:
            return False
    return pattern.lower() in text.lower()


def _signal_matches(signal: PolicySignal, features: PolicyFeatures) -> bool:
    pattern = signal.pattern.strip()
    if pattern.startswith("feature:"):
        return features.has(pattern.removeprefix("feature:").strip())
    return _pattern_matches(pattern, features.text)


def _best_feature_pattern(signal_type: str, features: PolicyFeatures) -> str | None:
    priority = (
        [
            "short_followup",
            "continuity_reference",
            "preference_reference",
            "project_context_reference",
            "task_work_intent",
            "memory_reference",
        ]
        if signal_type == "read"
        else [
            "explicit_memory_intent",
            "future_instruction",
            "decision_statement",
            "correction_statement",
            "identity_statement",
            "preference_statement",
            "goal_statement",
            "style_instruction",
        ]
    )
    for name in priority:
        if features.has(name):
            return f"feature:{name}"
    return None


def _looks_like_regex(pattern: str) -> bool:
    return "\\" in pattern or "(?:" in pattern or "(?!" in pattern or "(?<" in pattern


def _initial_status(confidence: float) -> str:
    if confidence >= 0.85:
        return "stable"
    if confidence >= 0.62:
        return "active"
    return "candidate"
