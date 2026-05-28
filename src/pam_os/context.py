from __future__ import annotations

from collections import defaultdict

from pam_os.models import ContextPackage, Memory, SearchResult, new_id
from pam_os.models import ProfileTrait


SECTION_TITLES = {
    "identity": "Identity",
    "preference": "Long-term Preferences",
    "project": "Active Projects",
    "goal": "Current Goals",
    "style": "Response Guidance",
    "episodic": "Relevant Recent Events",
    "semantic": "Useful Facts",
}


class ContextCompiler:
    def compile(
        self,
        task: str,
        results: list[SearchResult],
        *,
        max_chars: int | None = None,
        profile_traits: list[ProfileTrait] | None = None,
    ) -> ContextPackage:
        memories = self._dedupe([result.memory for result in results])
        grouped: dict[str, list[Memory]] = defaultdict(list)
        for memory in memories:
            grouped[memory.type].append(memory)

        lines = ["# User Memory Context", "", f"Current task: {task}", ""]
        profile_traits = profile_traits or []
        if profile_traits:
            lines.append("## User Profile")
            for trait in profile_traits:
                lines.append(
                    f"- {trait.statement} "
                    f"(stability={trait.stability:.2f}, confidence={trait.confidence:.2f}, evidence={trait.evidence_count})"
                )
            lines.append("")
        for memory_type in ["identity", "preference", "project", "goal", "style", "episodic", "semantic"]:
            entries = grouped.get(memory_type, [])
            if not entries:
                continue
            lines.append(f"## {SECTION_TITLES[memory_type]}")
            for memory in sorted(entries, key=lambda item: (item.importance, item.confidence), reverse=True):
                tags = f" [{', '.join(memory.tags)}]" if memory.tags else ""
                lines.append(
                    f"- {memory.content}{tags} "
                    f"(importance={memory.importance:.2f}, confidence={memory.confidence:.2f})"
                )
            lines.append("")

        if len(lines) <= 4:
            lines.extend(["## No Relevant Memories", "- No matching long-term memories were found.", ""])

        content = "\n".join(lines).strip() + "\n"
        if max_chars and len(content) > max_chars:
            content = content[: max_chars - 32].rstrip() + "\n\n[truncated]\n"

        return ContextPackage(
            id=new_id("ctx"),
            task=task,
            content=content,
            memory_ids=[memory.id for memory in memories],
        )

    def _dedupe(self, memories: list[Memory]) -> list[Memory]:
        seen: set[str] = set()
        deduped: list[Memory] = []
        for memory in memories:
            key = " ".join(memory.content.lower().split())
            if key in seen:
                continue
            seen.add(key)
            deduped.append(memory)
        return deduped
