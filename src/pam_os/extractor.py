from __future__ import annotations

import json
import re
from typing import Any, Protocol

from pam_os.models import Memory, new_id, now_iso


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

        memories = self._extract_rule_based(event_id, content)
        if memories:
            return memories

        return [self._memory_from_content(event_id, content, self._infer_type(content))]

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
        memories: list[Memory] = []
        identity = self._extract_identity_name(content)
        if identity:
            memories.append(self._memory_from_content(event_id, f"用户姓名是{identity}", "identity"))
        else:
            memory_type = self._infer_type(content)
            if memory_type in {"preference", "goal", "project", "style"}:
                memories.append(self._memory_from_content(event_id, content, memory_type))
                return self._dedupe_memories(memories)

        for clause in self._stable_clauses(content):
            memory_type = self._infer_type(clause)
            if memory_type in {"preference", "goal", "project", "style"}:
                memories.append(self._memory_from_content(event_id, clause, memory_type))

        return self._dedupe_memories(memories)

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
            r"\bmy name is\s+([A-Za-z][A-Za-z0-9_\-]{1,31})\b",
            r"\bi am called\s+([A-Za-z][A-Za-z0-9_\-]{1,31})\b",
            r"\bi'm called\s+([A-Za-z][A-Za-z0-9_\-]{1,31})\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, content, flags=re.IGNORECASE)
            if match:
                candidate = match.group(1).strip()
                if self._looks_like_identity_name(candidate):
                    return candidate
        return None

    def _looks_like_identity_name(self, candidate: str) -> bool:
        if re.fullmatch(r"[\u4e00-\u9fff]{2,8}", candidate):
            return not candidate.startswith(("一个", "一名", "个", "名"))
        return re.fullmatch(r"[A-Za-z][A-Za-z0-9_\-]{1,31}", candidate) is not None

    def _stable_clauses(self, content: str) -> list[str]:
        return [clause.strip() for clause in re.split(r"[，,。；;！!？?\n]+", content) if clause.strip()]

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

    def _infer_type(self, content: str) -> str:
        lower = content.lower()
        if any(token in content for token in ["偏好", "喜欢", "不喜欢", "倾向", "更希望"]) or any(
            token in lower for token in ["prefer", "preference", "like", "dislike"]
        ):
            return "preference"
        if any(token in content for token in ["回答风格", "风格", "语气"]) or "style" in lower:
            return "style"
        if any(token in content for token in ["目标", "希望能够", "计划", "下一步"]) or any(
            token in lower for token in ["goal", "plan", "next step"]
        ):
            return "goal"
        if any(token in content for token in ["项目", "正在做", "正在设计", "MVP", "OS"]) or any(
            token in lower for token in ["project", "mvp"]
        ):
            return "project"
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
