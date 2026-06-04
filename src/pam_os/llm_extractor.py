from __future__ import annotations

import json
import re
from typing import Any, Protocol

from pam_os.extractor import MEMORY_TYPES, RuleBasedExtractor
from pam_os.models import Memory, new_id, now_iso


class LlmExtractionClient(Protocol):
    def extract_memories(self, content: str, metadata: dict[str, Any]) -> str | dict[str, Any] | list[Any]:
        ...


class LlmMemoryExtractor:
    """Optional LLM-backed extractor with deterministic validation and fallback."""

    def __init__(self, client: LlmExtractionClient, fallback: RuleBasedExtractor | None = None):
        self.client = client
        self.fallback = fallback or RuleBasedExtractor()

    def extract(self, event_id: str, content: str, metadata: dict[str, Any]) -> list[Memory]:
        try:
            payload = self.client.extract_memories(content, metadata)
            memories = self._memories_from_payload(event_id, content, payload)
        except Exception:
            return self.fallback.extract(event_id, content, metadata)
        if not memories:
            return self.fallback.extract(event_id, content, metadata)
        return memories

    def _memories_from_payload(self, event_id: str, source: str, payload: str | dict[str, Any] | list[Any]) -> list[Memory]:
        parsed = self._parse_payload(payload)
        if parsed is None:
            return []

        raw_items = parsed.get("memories", []) if isinstance(parsed, dict) else parsed
        if not isinstance(raw_items, list):
            return []

        timestamp = now_iso()
        memories: list[Memory] = []
        for item in raw_items:
            memory = self._memory_from_item(event_id, source, item, timestamp)
            if memory is not None:
                memories.append(memory)
        return self._dedupe_memories(memories)

    def _parse_payload(self, payload: str | dict[str, Any] | list[Any]) -> dict[str, Any] | list[Any] | None:
        if isinstance(payload, (dict, list)):
            return payload
        text = payload.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            text = fenced.group(1).strip()
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, (dict, list)) else None

    def _memory_from_item(self, event_id: str, source: str, item: Any, timestamp: str) -> Memory | None:
        if not isinstance(item, dict):
            return None
        content = str(item.get("content", "")).strip()
        if not content:
            return None

        evidence = str(item.get("evidence", "")).strip()
        if evidence and evidence not in source:
            return None

        memory_type = str(item.get("type", "semantic")).strip().lower()
        if memory_type not in MEMORY_TYPES:
            memory_type = "semantic"

        tags = self._validated_tags(item.get("tags", []))
        fact_key = str(item.get("fact_key", "")).strip()
        if fact_key:
            tags.append(f"fact:{fact_key}")

        return Memory(
            id=new_id("mem"),
            event_id=event_id,
            type=memory_type,
            content=content,
            importance=self._clamp_float(item.get("importance", 0.6)),
            confidence=self._clamp_float(item.get("confidence", 0.7)),
            tags=sorted(set(tags)),
            created_at=timestamp,
            updated_at=timestamp,
        )

    def _validated_tags(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [tag for tag in (str(item).strip() for item in value) if tag]

    def _clamp_float(self, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            number = 0.5
        return max(0.0, min(1.0, number))

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
