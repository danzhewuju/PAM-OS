from __future__ import annotations

from pam_os.config import ConsolidationConfig
from pam_os.rule_provider import RuleProfileConsolidator, TraitCandidate
from pam_os.store import MemoryStore


class MemoryConsolidator(RuleProfileConsolidator):
    """Backward-compatible name for the default local profile consolidator."""

    def __init__(self, store: MemoryStore, config: ConsolidationConfig | None = None):
        super().__init__(store, config=config)


__all__ = ["MemoryConsolidator", "RuleProfileConsolidator", "TraitCandidate"]
