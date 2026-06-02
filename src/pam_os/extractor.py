from __future__ import annotations

import json
import re
from typing import Any, Protocol

from pam_os.models import Memory, MemoryFactCandidate, new_id, now_iso


MEMORY_TYPES = {"semantic", "episodic", "identity", "preference", "goal", "project", "style"}


class Extractor(Protocol):
    def extract(self, event_id: str, content: str, metadata: dict[str, Any]) -> list[Memory]:
        ...


class RuleBasedExtractor:
    """Small deterministic extractor for v0.1.

    It accepts explicit JSON memories when present, otherwise creates one useful
    structured memory from the event text.
    """

    def extract(self, event_id: str, content: str, metadata: dict[str, Any]) -> list[Memory]:
        explicit = self._extract_explicit_json(event_id, content)
        if explicit:
            return explicit

        facts = self.extract_facts(content)
        if facts:
            return self._dedupe_memories([self._memory_from_fact(event_id, fact) for fact in facts])

        return [self._memory_from_content(event_id, content, self._infer_type(content))]

    def extract_facts(self, content: str) -> list[MemoryFactCandidate]:
        facts: list[MemoryFactCandidate] = []
        if self._is_project_decision(content):
            return [self._fact_from_content("project", content)]

        facts.extend(self._extract_identity_facts(content))
        if not facts:
            memory_type = self._infer_type(content)
            if memory_type in {"preference", "goal", "project", "style"}:
                return self._dedupe_facts([self._fact_from_content(memory_type, content)])

        for clause in self._stable_clauses(content):
            facts.extend(self._extract_identity_facts(clause))
            memory_type = self._infer_type(clause)
            if memory_type in {"preference", "goal", "project", "style"}:
                facts.append(self._fact_from_content(memory_type, clause))

        return self._dedupe_facts(facts)

    def _extract_explicit_json(self, event_id: str, content: str) -> list[Memory]:
        payload = self._parse_json_payload(content)
        if payload is None:
            return []
        items = payload if isinstance(payload, list) else [payload]
        memories: list[Memory] = []
        timestamp = now_iso()
        for item in items:
            if not isinstance(item, dict) or "content" not in item:
                continue
            memory_type = str(item.get("type", "semantic")).strip().lower()
            if memory_type not in MEMORY_TYPES:
                memory_type = "semantic"
            memories.append(
                Memory(
                    id=new_id("mem"),
                    event_id=event_id,
                    type=memory_type,
                    content=str(item["content"]).strip(),
                    importance=self._clamp_float(item.get("importance", 0.6)),
                    confidence=self._clamp_float(item.get("confidence", 0.7)),
                    tags=[str(tag).strip() for tag in item.get("tags", []) if str(tag).strip()],
                    created_at=timestamp,
                    updated_at=timestamp,
                )
            )
        return memories

    def _extract_rule_based(self, event_id: str, content: str) -> list[Memory]:
        return self._dedupe_memories([self._memory_from_fact(event_id, fact) for fact in self.extract_facts(content)])

    def _fact_from_content(self, memory_type: str, evidence: str, *, value: str | None = None) -> MemoryFactCandidate:
        key = self._infer_fact_key(evidence, memory_type)
        value = value or self._infer_fact_value(evidence, memory_type)
        tags = {*self._infer_tags(evidence, memory_type), f"fact:{key}"}
        return MemoryFactCandidate(
            type=memory_type,
            key=key,
            value=value,
            evidence=evidence.strip(),
            content=self._normalize_content(evidence, memory_type),
            importance=self._infer_importance(evidence, memory_type),
            confidence=0.72 if memory_type in {"identity", "preference", "goal", "project", "style"} else 0.62,
            tags=sorted(tags),
        )

    def _memory_from_fact(self, event_id: str, fact: MemoryFactCandidate) -> Memory:
        timestamp = now_iso()
        return Memory(
            id=new_id("mem"),
            event_id=event_id,
            type=fact.type,
            content=fact.content,
            importance=fact.importance,
            confidence=fact.confidence,
            tags=fact.tags,
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _memory_from_content(self, event_id: str, content: str, memory_type: str) -> Memory:
        timestamp = now_iso()
        return Memory(
            id=new_id("mem"),
            event_id=event_id,
            type=memory_type,
            content=self._normalize_content(content, memory_type),
            importance=self._infer_importance(content, memory_type),
            confidence=0.72 if memory_type in {"identity", "preference", "goal", "project", "style"} else 0.62,
            tags=self._infer_tags(content, memory_type),
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _extract_identity_name(self, content: str) -> str | None:
        patterns = [
            r"(?:我是|我叫|用户叫|用户姓名是|我的名字是|我的姓名是)\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9_\-·]{1,31})",
            r"用户身份信息[:：]\s*(?:用户姓名是|用户叫)?\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9_\-·]{1,31})",
            r"\bthe user is called\s+([A-Za-z][A-Za-z0-9_\-]{1,31})\b",
            r"\buser is called\s+([A-Za-z][A-Za-z0-9_\-]{1,31})\b",
            r"\bthe user(?:'s)? name is\s+([A-Za-z][A-Za-z0-9_\-]{1,31})\b",
            r"\buser(?:'s|s)? name is\s+([A-Za-z][A-Za-z0-9_\-]{1,31})\b",
            r"\bplease call me\s+([A-Za-z][A-Za-z0-9_\-]{1,31})\b",
            r"\bcall me\s+([A-Za-z][A-Za-z0-9_\-]{1,31})\b",
            r"叫我\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9_\-·]{1,31})",
            r"称呼我\s*([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9_\-·]{1,31})",
            r"\bmy name is\s+([A-Za-z][A-Za-z0-9_\-]{1,31})\b",
            r"\bi am called\s+([A-Za-z][A-Za-z0-9_\-]{1,31})\b",
            r"\bi'm called\s+([A-Za-z][A-Za-z0-9_\-]{1,31})\b",
            r"\bi am\s+([A-Za-z][A-Za-z0-9_\-]{1,31})\b",
            r"\bi'm\s+([A-Za-z][A-Za-z0-9_\-]{1,31})\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, content, flags=re.IGNORECASE)
            if match:
                candidate = match.group(1).strip()
                if self._looks_like_identity_name(candidate):
                    return candidate
        return None

    def _extract_identity_facts(self, content: str) -> list[MemoryFactCandidate]:
        facts: list[MemoryFactCandidate] = []
        name = self._extract_identity_name(content)
        if name:
            facts.append(self._fact_from_content("identity", f"用户姓名是{name}", value=name))

        for value, evidence in [
            (self._extract_identity_role(content), "用户职业/角色是{}"),
            (self._extract_identity_location(content), "用户所在地是{}"),
            (self._extract_identity_timezone(content), "用户时区是{}"),
            (self._extract_identity_language(content), "用户使用语言是{}"),
        ]:
            if value:
                facts.append(self._fact_from_content("identity", evidence.format(value), value=value))
        return facts

    def _extract_identity_role(self, content: str) -> str | None:
        patterns = [
            r"(?:我的职业是|我的角色是|我从事|用户职业是|用户角色是|用户身份是)\s*([^，,。；;！!？?\n]{2,48})",
            r"(?:我是|用户是)(?:一名|一位|一个)?\s*([^，,。；;！!？?\n]{2,48})",
            r"\bmy role is\s+(?:a |an )?([^,.;!?\n]{2,48})",
            r"\bi work as\s+(?:a |an )?([^,.;!?\n]{2,48})",
            r"\b(?:the user|user)(?:'s)? role is\s+(?:a |an )?([^,.;!?\n]{2,48})",
            r"\b(?:the user|user) works as\s+(?:a |an )?([^,.;!?\n]{2,48})",
            r"\b(?:the user|user) is\s+(?:a |an )?([^,.;!?\n]{2,48})",
        ]
        for pattern in patterns:
            match = re.search(pattern, content, flags=re.IGNORECASE)
            if match:
                candidate = self._trim_identity_candidate(match.group(1))
                if self._looks_like_identity_role(candidate):
                    return candidate
        return None

    def _extract_identity_location(self, content: str) -> str | None:
        patterns = [
            r"(?:我住在|我常驻|我位于|我的所在地是|我的城市是|用户住在|用户常驻|用户位于|用户所在地是|用户城市是)\s*([^，,。；;！!？?\n]{2,48})",
            r"\bi(?:'m| am) based in\s+([^,.;!?\n]{2,48})",
            r"\bi live in\s+([^,.;!?\n]{2,48})",
            r"\bmy location is\s+([^,.;!?\n]{2,48})",
            r"\b(?:the user|user) is based in\s+([^,.;!?\n]{2,48})",
            r"\b(?:the user|user) lives in\s+([^,.;!?\n]{2,48})",
        ]
        for pattern in patterns:
            match = re.search(pattern, content, flags=re.IGNORECASE)
            if match:
                candidate = self._trim_identity_candidate(match.group(1))
                if self._looks_like_identity_place(candidate):
                    return candidate
        return None

    def _extract_identity_timezone(self, content: str) -> str | None:
        patterns = [
            r"(?:我的时区是|用户时区是)\s*([^，,。；;！!？?\n]{2,32})",
            r"\bmy timezone is\s+([^,.;!?\n]{2,32})",
            r"\b(?:the user|user)(?:'s)? timezone is\s+([^,.;!?\n]{2,32})",
        ]
        for pattern in patterns:
            match = re.search(pattern, content, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" 。.，,")
        return None

    def _extract_identity_language(self, content: str) -> str | None:
        patterns = [
            r"(?:我会说|我使用语言是|用户会说|用户使用语言是)\s*([^，,。；;！!？?\n]{2,48})",
            r"\bi speak\s+([^,.;!?\n]{2,48})",
            r"\b(?:the user|user) speaks\s+([^,.;!?\n]{2,48})",
        ]
        for pattern in patterns:
            match = re.search(pattern, content, flags=re.IGNORECASE)
            if match:
                return match.group(1).strip(" 。.，,")
        return None

    def _trim_identity_candidate(self, candidate: str) -> str:
        trimmed = candidate.strip(" 。.，,")
        return re.split(r"\s+and\s+(?=(?:i|i'm|they|user|the user)\s+)", trimmed, maxsplit=1)[0].strip(" 。.，,")

    def _looks_like_identity_name(self, candidate: str) -> bool:
        role_tokens = {
            "工程师",
            "开发",
            "程序员",
            "产品",
            "设计",
            "学生",
            "老师",
            "教师",
            "创始",
            "经理",
            "研究",
            "作者",
            "运营",
            "架构",
            "developer",
            "engineer",
            "designer",
            "student",
            "teacher",
            "founder",
            "manager",
            "researcher",
            "writer",
            "operator",
            "consultant",
        }
        lower_candidate = candidate.lower()
        if any(token in candidate or token in lower_candidate for token in role_tokens):
            return False
        if re.fullmatch(r"[\u4e00-\u9fff]{2,8}", candidate):
            return not candidate.startswith(("一个", "一名", "个", "名"))
        non_names = {
            "called",
            "doing",
            "going",
            "working",
            "using",
            "trying",
            "planning",
            "building",
            "learning",
            "interested",
            "curious",
            "happy",
            "glad",
            "sorry",
            "sure",
            "here",
            "not",
        }
        if lower_candidate in non_names:
            return False
        return re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-]{1,31}", candidate) is not None

    def _looks_like_identity_role(self, candidate: str) -> bool:
        lower = candidate.lower()
        role_tokens = [
            "工程师",
            "开发",
            "程序员",
            "产品",
            "设计",
            "学生",
            "老师",
            "教师",
            "创始",
            "经理",
            "研究",
            "作者",
            "运营",
            "架构",
            "developer",
            "engineer",
            "designer",
            "student",
            "teacher",
            "founder",
            "manager",
            "researcher",
            "writer",
            "operator",
            "consultant",
        ]
        if any(token in candidate or token in lower for token in role_tokens):
            return True
        if self._looks_like_identity_name(candidate):
            return False
        return False

    def _looks_like_identity_place(self, candidate: str) -> bool:
        lower = candidate.lower()
        if len(candidate.strip()) < 2:
            return False
        if any(token in lower for token in ["doing", "working", "building", "using"]):
            return False
        return True

    def _stable_clauses(self, content: str) -> list[str]:
        split_pattern = (
            r"[，,。；;！!？?\n]+"
            r"|\s+and\s+(?=(?:i|i'm|they|user|the user)\s+"
            r"(?:like|likes|prefer|prefers|work|works|live|lives|speak|speaks|use|uses|usually|mainly|mostly|am|is)\b)"
        )
        return [clause.strip() for clause in re.split(split_pattern, content) if clause.strip()]

    def _dedupe_facts(self, facts: list[MemoryFactCandidate]) -> list[MemoryFactCandidate]:
        seen: set[tuple[str, str, str]] = set()
        deduped: list[MemoryFactCandidate] = []
        for fact in facts:
            key = (fact.type, fact.key, " ".join(fact.value.lower().split()))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(fact)
        return deduped

    def _dedupe_memories(self, memories: list[Memory]) -> list[Memory]:
        seen: set[tuple[str, str]] = set()
        deduped: list[Memory] = []
        for memory in memories:
            key = (memory.type, " ".join(memory.content.lower().split()))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(memory)
        return deduped

    def _parse_json_payload(self, content: str) -> Any | None:
        text = content.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            text = fenced.group(1).strip()
        if not (text.startswith("{") or text.startswith("[")):
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def _infer_fact_key(self, content: str, memory_type: str) -> str:
        lower = content.lower()
        if memory_type == "identity":
            if any(token in content for token in ["姓名", "名字", "叫"]) or any(
                token in lower for token in ["name", "called", "call me"]
            ):
                return "profile.identity.name"
            if any(token in content for token in ["职业", "角色", "身份", "从事"]) or any(
                token in lower for token in ["role", "work as", "works as", "developer", "engineer", "designer", "student", "founder"]
            ):
                return "profile.identity.role"
            if any(token in content for token in ["所在地", "城市", "住在", "常驻", "位于"]) or any(
                token in lower for token in ["based in", "live in", "lives in", "location"]
            ):
                return "profile.identity.location"
            if "时区" in content or "timezone" in lower:
                return "profile.identity.timezone"
            if any(token in content for token in ["语言", "会说"]) or "speak" in lower:
                return "profile.identity.language"
            return "profile.identity"
        if memory_type == "preference":
            if any(token in content for token in ["喜欢", "感兴趣", "平时用", "常用", "主要用", "技术栈"]) or any(
                token in lower
                for token in [
                    "i like",
                    "i prefer",
                    "they like",
                    "they prefer",
                    "user likes",
                    "user prefers",
                    "the user likes",
                    "the user prefers",
                    "interested in",
                    "usually use",
                    "mainly use",
                    "mostly use",
                    "usual stack",
                    "my stack",
                ]
            ):
                return "preference.interests"
            return "general.preference"
        if memory_type == "style":
            return "communication.answer_style"
        if memory_type == "goal":
            return "long_term.goal"
        if memory_type == "project":
            if any(token in content for token in ["决定", "先用", "不引入"]) or any(
                token in lower for token in ["decided", "decision", "will use", "should use", "not introduce"]
            ):
                return "project.technical_decision"
            return "project.active_context"
        return f"memory.{memory_type}"

    def _infer_fact_value(self, content: str, memory_type: str) -> str:
        stripped = " ".join(content.strip().split())
        if memory_type == "preference":
            patterns = [
                r"\bi like\s+(.+)$",
                r"\bi prefer\s+(.+)$",
                r"\bthey like\s+(.+)$",
                r"\bthey prefer\s+(.+)$",
                r"\buser likes\s+(.+)$",
                r"\buser prefers\s+(.+)$",
                r"\bthe user likes\s+(.+)$",
                r"\bthe user prefers\s+(.+)$",
                r"\bi usually use\s+(.+)$",
                r"\bi mainly use\s+(.+)$",
                r"\bi mostly use\s+(.+)$",
                r"\bmy usual stack is\s+(.+)$",
                r"\bmy stack is\s+(.+)$",
                r"\buser usually uses\s+(.+)$",
                r"\bthe user usually uses\s+(.+)$",
                r"我喜欢(.+)$",
                r"我偏好(.+)$",
                r"我平时用(.+)$",
                r"我常用(.+)$",
                r"我主要用(.+)$",
                r"我的技术栈是(.+)$",
            ]
            for pattern in patterns:
                match = re.search(pattern, stripped, flags=re.IGNORECASE)
                if match:
                    return match.group(1).strip(" 。.，,")
        return stripped.strip(" 。.，,")

    def _is_project_decision(self, content: str) -> bool:
        lower = content.lower()
        return "项目决策" in content or "project decision" in lower

    def _infer_type(self, content: str) -> str:
        lower = content.lower()
        if any(token in content for token in ["回答风格", "风格", "语气"]) or "style" in lower:
            return "style"
        if any(token in content for token in ["目标", "希望能够", "计划", "下一步"]) or any(
            token in lower for token in ["goal", "plan", "next step"]
        ):
            return "goal"
        if self._is_project_decision(content) or any(token in content for token in ["项目", "正在做", "正在设计", "MVP"]) or any(
            token in lower for token in ["project", "mvp"]
        ):
            return "project"
        if any(token in content for token in ["偏好", "喜欢", "不喜欢", "倾向", "更希望", "平时用", "常用", "主要用", "技术栈"]) or any(
            token in lower for token in ["prefer", "preference", "like", "dislike", "usually use", "mainly use", "mostly use", "usual stack", "my stack"]
        ):
            return "preference"
        if any(token in content for token in ["今天", "昨天", "最近", "刚刚"]):
            return "episodic"
        return "semantic"

    def _infer_tags(self, content: str, memory_type: str) -> list[str]:
        tags = {memory_type}
        keyword_map = {
            "self-host": ["self-host", "自托管", "本地", "可控"],
            "memory-os": ["Memory OS", "Memory", "记忆"],
            "infra": ["Flink", "Kafka", "Qdrant", "Neo4j", "infra", "基础设施"],
            "engineering": ["工程", "实现", "落地", "技术"],
            "siyuan": ["SiYuan", "思源"],
            "cli": ["CLI", "命令行"],
        }
        for tag, needles in keyword_map.items():
            if any(needle in content for needle in needles):
                tags.add(tag)
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", content):
            tags.add(token.lower())
        return sorted(tags)

    def _infer_importance(self, content: str, memory_type: str) -> float:
        base = {
            "identity": 0.9,
            "preference": 0.82,
            "goal": 0.78,
            "project": 0.8,
            "style": 0.75,
            "semantic": 0.62,
            "episodic": 0.58,
        }[memory_type]
        if any(token in content for token in ["长期", "核心", "必须", "不应", "MVP", "偏好"]):
            base += 0.08
        return min(base, 0.95)

    def _normalize_content(self, content: str, memory_type: str) -> str:
        stripped = " ".join(content.strip().split())
        if memory_type == "identity" and not stripped.startswith("用户"):
            return f"用户身份信息：{stripped}"
        if memory_type == "preference" and not stripped.startswith("用户"):
            return f"用户偏好/倾向：{stripped}"
        if memory_type == "project" and not stripped.startswith("用户"):
            return f"用户项目上下文：{stripped}"
        if memory_type == "goal" and not stripped.startswith("用户"):
            return f"用户目标/计划：{stripped}"
        return stripped

    def _clamp_float(self, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 0.5
        return max(0.0, min(1.0, number))
