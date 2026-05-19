from __future__ import annotations

from pam_os.config import load_config
from pam_os.runtime import PersonalMemoryRuntime


def test_memory_roundtrip(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    result = runtime.remember(
        "我今天在思考 Personal AI Memory OS，倾向先做本地 MCP Server，不想一开始引入重型组件。"
    )

    assert result["event"].content
    assert result["memories"]

    results = runtime.search_memory("Personal AI Memory OS 下一步实现", limit=5)
    assert results
    assert "Personal AI Memory OS" in results[0].memory.content

    package = runtime.compile_context("我现在想继续做 Personal AI Memory OS，下一步怎么做？")
    assert "User Memory Context" in package.content
    assert "Personal AI Memory OS" in package.content


def test_explicit_json_extraction(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    runtime.remember(
        """
        [
          {
            "type": "preference",
            "content": "用户偏好 self-host 和本地可控系统。",
            "importance": 0.9,
            "confidence": 0.85,
            "tags": ["self-host", "control"]
          }
        ]
        """
    )

    package = runtime.compile_context("给我一个符合我偏好的实现方案")
    assert "self-host" in package.content
    assert "Long-term Preferences" in package.content


def test_prepare_context_gates_generic_questions(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")
    runtime.remember("用户偏好 self-host 和本地可控系统。")

    prepared = runtime.prepare_context("Python list 怎么排序？")

    assert prepared.decision.should_use is False
    assert prepared.package is None


def test_prepare_context_returns_budgeted_context(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")
    runtime.capture_memory(
        "我决定 Personal AI Memory OS v0.1 先用 SQLite FTS5，不引入 Qdrant。",
        force=True,
    )
    runtime.capture_memory("我偏好直接、工程化、可执行的回答。", force=True)

    prepared = runtime.prepare_context("我继续做 Personal AI Memory OS，下一步怎么做？")

    assert prepared.decision.should_use is True
    assert prepared.package is not None
    assert "Personal AI Memory OS" in prepared.package.content
    assert prepared.results


def test_capture_memory_skips_transient_content(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    skipped = runtime.capture_memory("哈哈好的")
    captured = runtime.capture_memory("我偏好 self-host、开源、可控系统。")

    assert skipped.should_capture is False
    assert captured.should_capture is True
    assert captured.memories


def test_behavior_choice_consolidates_into_profile_trait(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    runtime.record_behavior_choice(
        context="PAM-OS 技术路线",
        chosen=["SQLite FTS5"],
        rejected=["Qdrant", "Neo4j"],
        reason="MVP 阶段先保持本地、轻量、可控",
    )

    result = runtime.consolidate_memory(recent=100)
    traits = runtime.get_user_profile(query="Personal AI Memory OS 技术路线")

    assert result.evidence_created
    assert any(trait.trait_key == "technical.decision_style" for trait in traits)


def test_prepare_context_includes_profile_traits(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    runtime.capture_memory("我偏好 self-host、开源、可控系统。", force=True)
    runtime.consolidate_memory(recent=100)

    prepared = runtime.prepare_context("我继续做 Personal AI Memory OS，下一步怎么做？", force=True)

    assert prepared.package is not None
    assert "User Profile" in prepared.package.content
    assert "self-host" in prepared.package.content


def test_config_file_controls_defaults(tmp_path):
    config_path = tmp_path / "pam-os.toml"
    db_path = tmp_path / "configured.sqlite3"
    config_path.write_text(
        f"""
[storage]
db_path = "{db_path.as_posix()}"

[context]
default_limit = 2
max_chars = 180
profile_limit = 1

[consolidation]
recent_limit = 5

[profile]
default_limit = 1
""",
        encoding="utf-8",
    )

    config = load_config(config_path)
    runtime = PersonalMemoryRuntime(config=config)
    assert runtime.db_path == db_path

    runtime.capture_memory("我偏好 self-host、开源、可控系统。", force=True)
    runtime.record_behavior_choice(
        context="PAM-OS 技术路线",
        chosen=["SQLite FTS5"],
        rejected=["Qdrant"],
        reason="本地轻量可控",
    )
    runtime.consolidate_memory()

    traits = runtime.get_user_profile()
    prepared = runtime.prepare_context("我继续做 Personal AI Memory OS，下一步怎么做？", force=True)

    assert len(traits) == 1
    assert prepared.package is not None
    assert len(prepared.package.content) <= 180
