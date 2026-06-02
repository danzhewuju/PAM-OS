from __future__ import annotations

import json

from pam_os.api import create_app
from pam_os.cli import main
from pam_os.config import AppConfig, ConsolidationConfig, load_config
from pam_os.models import ConsolidationResult, MemoryUseDecision, SearchResult
from pam_os.runtime import PersonalMemoryRuntime
from pam_os.version import __version__


class AlwaysReadPolicy:
    def decide_read(self, task, conversation_summary=None):
        return MemoryUseDecision(True, "fake read policy", 0.99, ["fake"])

    def decide_capture(self, content, metadata=None):
        return MemoryUseDecision(True, "fake capture policy", 0.99, ["fake"])


class NeverCapturePolicy:
    def decide_read(self, task, conversation_summary=None):
        return MemoryUseDecision(False, "fake no read policy", 0.99, ["fake"])

    def decide_capture(self, content, metadata=None):
        return MemoryUseDecision(False, "fake no capture policy", 0.99, ["fake"])


class StaticRetriever:
    def __init__(self, results):
        self.results = results
        self.queries = []

    def retrieve(
        self,
        query,
        *,
        limit,
        types=None,
        min_importance=0.0,
        min_confidence=0.0,
    ):
        self.queries.append(query)
        return self.results[:limit]


class ReverseReranker:
    def rerank(self, query, results):
        return list(reversed(results))


class EmptyConsolidator:
    def __init__(self):
        self.calls = 0

    def consolidate(self, *, recent=100):
        self.calls += 1
        return ConsolidationResult(memories_scanned=recent, behavior_events_scanned=0)


def test_memory_roundtrip(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    result = runtime.remember(
        "我今天在思考 Personal AI Memory OS，倾向先做本地 REST 服务，不想一开始引入重型组件。"
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


def test_task_work_phrasing_triggers_project_memory(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    examples = [
        "pamr 帮我排查一下插件安装失败",
        "帮我排查一下插件安装失败",
        "帮我分析一下这个项目为什么不会触发 PAM",
        "解决一下",
        "优化一下这个项目",
    ]

    for example in examples:
        decision = runtime.should_use_memory(example)

        assert decision.should_use is True
        assert set(decision.signals) & {"task_work_reference", "task_work_intent"}


def test_english_phrasing_triggers_project_memory(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    examples = [
        ("help me debug this repo", "task_work_intent"),
        ("continue where we left off", "history_reference"),
        ("use my usual style for this project", "preference_reference"),
        ("as we discussed, optimize the current codebase", "continuity_reference"),
    ]

    for example, expected_signal in examples:
        decision = runtime.should_use_memory(example)

        assert decision.should_use is True
        assert expected_signal in decision.signals


def test_english_read_markers_use_word_boundaries(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    decision = runtime.should_use_memory("mypy prefix issue")

    assert decision.should_use is False
    assert decision.signals == []


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


def test_capture_identity_and_preference_sentence_splits_memories(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    captured = runtime.capture_memory("我是余豪，我喜欢本地优先的工具。")

    assert captured.should_capture is True
    assert {memory.type for memory in captured.memories} == {"identity", "preference"}
    assert any("用户姓名是余豪" in memory.content for memory in captured.memories)
    assert any("我喜欢本地优先的工具" in memory.content for memory in captured.memories)

    runtime.consolidate_memory(recent=100)
    trait_keys = {trait.trait_key for trait in runtime.get_user_profile()}

    assert "profile.identity.name" in trait_keys
    assert "preference.interests" in trait_keys


def test_english_identity_and_preference_roundtrip(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    captured = runtime.capture_memory("Hello, I'm Alex, I like digital products.")
    prepared = runtime.prepare_context("Hello, who am I?")

    assert captured.should_capture is True
    assert {memory.type for memory in captured.memories} == {"identity", "preference"}
    identity = next(memory for memory in captured.memories if memory.type == "identity")
    preference = next(memory for memory in captured.memories if memory.type == "preference")

    assert identity.content == "用户姓名是Alex"
    assert "fact:profile.identity.name" in identity.tags
    assert "I like digital products" in preference.content
    assert "fact:preference.interests" in preference.tags
    assert prepared.decision.should_use is True
    assert prepared.package is not None
    assert "用户姓名是Alex" in prepared.package.content
    assert "I like digital products" in prepared.package.content

    interests = runtime.prepare_context("What are my interests?")

    assert interests.decision.should_use is True
    assert interests.package is not None
    assert "I like digital products" in interests.package.content

    runtime.consolidate_memory(recent=100)
    trait_keys = {trait.trait_key for trait in runtime.get_user_profile()}

    assert "profile.identity.name" in trait_keys
    assert "preference.interests" in trait_keys


def test_identity_statement_without_preference_is_captured(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    captured = runtime.capture_memory("我叫余豪")

    assert captured.should_capture is True
    assert [memory.type for memory in captured.memories] == ["identity"]
    assert captured.memories[0].content == "用户姓名是余豪"


def test_user_identity_statement_is_captured_as_identity(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    captured = runtime.capture_memory("用户叫余豪。")

    assert captured.should_capture is True
    assert [memory.type for memory in captured.memories] == ["identity"]
    assert captured.memories[0].content == "用户姓名是余豪"


def test_identity_questions_recall_legacy_semantic_name_memory(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")
    runtime.remember(
        """
        {
          "type": "semantic",
          "content": "用户叫余豪。",
          "importance": 0.62,
          "confidence": 0.62,
          "tags": ["semantic"]
        }
        """
    )

    prepared = runtime.prepare_context("我是谁？")

    assert prepared.decision.should_use is True
    assert prepared.package is not None
    assert "用户叫余豪" in prepared.package.content
    assert prepared.package.memory_ids


def test_search_memory_merges_fts_and_like_for_semantic_results(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")
    runtime.remember(
        """
        {
          "type": "project",
          "content": "PAM-OS 是本地优先记忆运行时。",
          "importance": 0.8,
          "confidence": 0.8,
          "tags": ["pam-os", "project"]
        }
        """
    )
    runtime.remember(
        """
        {
          "type": "semantic",
          "content": "运行追踪会写入 quality_traces 表。",
          "importance": 0.9,
          "confidence": 0.9,
          "tags": ["semantic", "quality_traces"]
        }
        """
    )

    results = runtime.search_memory("PAM-OS 运行追踪", limit=10)

    assert any(result.memory.type == "semantic" for result in results)
    assert any("quality_traces" in result.memory.content for result in results)


def test_english_capture_phrasing_stores_stable_memory(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    examples = [
        "I prefer self-hosted tools with local control.",
        "We decided to use SQLite first and not introduce Qdrant.",
        "Next time, default to two options before recommending one.",
    ]

    for example in examples:
        captured = runtime.capture_memory(example)

        assert captured.should_capture is True
        assert captured.memories


def test_english_capture_skips_plain_questions(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    captured = runtime.capture_memory("I want to know how Python syntax works.")

    assert captured.should_capture is False
    assert captured.memories == []


def test_capture_memory_reinforces_duplicate_memory(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    first = runtime.capture_memory("我偏好 PAM-OS 的记忆写入自动一点，减少确认打扰。")
    second = runtime.capture_memory("我偏好 PAM-OS 的记忆写入自动一点，减少确认打扰。")
    stats = runtime.get_storage_stats()

    assert first.should_capture is True
    assert first.created_count == 1
    assert second.should_capture is True
    assert second.created_count == 0
    assert second.updated_count == 1
    assert first.memories[0].id == second.memories[0].id
    assert second.memories[0].confidence > first.memories[0].confidence
    assert stats.tables["memories"]["count"] == 1


def test_capture_memory_dedupes_similar_long_session_preferences(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    first = runtime.capture_memory("我偏好 PAM-OS 自动写入稳定偏好和项目决策。")
    second = runtime.capture_memory("我偏好 PAM-OS 自动写入稳定偏好和项目决策，不要频繁询问确认。")
    stats = runtime.get_storage_stats()

    assert first.created_count == 1
    assert second.created_count == 0
    assert second.updated_count == 1
    assert stats.tables["memories"]["count"] == 1
    assert "不要频繁询问确认" in second.memories[0].content


def test_capture_memory_still_creates_distinct_memory(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    runtime.capture_memory("我偏好 PAM-OS 自动写入稳定偏好和项目决策。")
    distinct = runtime.capture_memory("我偏好直接、工程化、可执行的回答。")
    stats = runtime.get_storage_stats()

    assert distinct.created_count == 1
    assert distinct.updated_count == 0
    assert stats.tables["memories"]["count"] == 2


def test_policy_provider_can_force_read_and_capture(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3", policy=AlwaysReadPolicy())

    captured = runtime.capture_memory("哈哈好的")
    prepared = runtime.prepare_context("Python list 怎么排序？")

    assert captured.should_capture is True
    assert captured.reason == "fake capture policy"
    assert prepared.decision.should_use is True
    assert prepared.decision.reason == "fake read policy"


def test_policy_provider_can_skip_capture(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3", policy=NeverCapturePolicy())

    captured = runtime.capture_memory("我偏好 self-host、开源、可控系统。")

    assert captured.should_capture is False
    assert captured.reason == "fake no capture policy"


def test_adaptive_policy_learns_read_signal(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")
    runtime.capture_memory("用户项目上下文：Aurora 项目正在做本地插件架构。", force=True)

    before = runtime.prepare_context("沿着 Aurora 那条线推进一下")
    signal = runtime.learn_policy_signal(
        signal_type="read",
        pattern="沿着 Aurora 那条线",
        normalized_intent="continue_project_thread",
        action="use_memory",
        scope="project",
        confidence=0.72,
    )
    after = runtime.prepare_context("沿着 Aurora 那条线推进一下")

    assert before.decision.should_use is False
    assert signal.status == "active"
    assert after.decision.should_use is True
    assert after.decision.reason == "learned policy signal matched"
    assert after.package is not None
    assert "Aurora" in after.package.content


def test_adaptive_feature_prior_handles_general_continuation(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    decision = runtime.should_use_memory("Pick up where we left off in the current codebase.")

    assert decision.should_use is True
    assert decision.reason == "adaptive feature signals indicate memory-dependent task"
    assert "continuity_reference" in decision.signals
    assert "project_context_reference" in decision.signals


def test_adaptive_policy_learns_read_feature_signal_from_feedback(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    before = runtime.should_use_memory("same one please")
    signal = runtime.learn_policy_signal_from_text(
        signal_type="read",
        text="same one please",
        normalized_intent="short_followup_continuation",
        action="use_memory",
        confidence=0.7,
    )
    after = runtime.should_use_memory("that one please")

    assert before.should_use is False
    assert signal.pattern == "feature:short_followup"
    assert after.should_use is True
    assert after.reason == "learned policy signal matched"
    assert "learned:short_followup_continuation" in after.signals


def test_policy_signal_raw_patterns_match_literal_text(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")
    runtime.learn_policy_signal(
        signal_type="read",
        pattern="C++ mode",
        normalized_intent="cpp_context",
        action="use_memory",
        confidence=0.7,
    )

    decision = runtime.should_use_memory("C++ mode")
    unrelated = runtime.should_use_memory("C mode")

    assert decision.should_use is True
    assert unrelated.should_use is False


def test_adaptive_policy_learns_capture_signal(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")
    runtime.learn_policy_signal(
        signal_type="capture",
        pattern="以后遇到这种情况",
        normalized_intent="durable_future_instruction",
        action="capture_memory",
        scope="workflow",
        confidence=0.7,
    )

    captured = runtime.capture_memory("以后遇到这种情况，默认先给我两个方案再推荐一个。")

    assert captured.should_capture is True
    assert captured.reason == "learned policy signal matched"
    assert captured.memories


def test_policy_signal_reinforcement_promotes_and_archives(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")
    runtime.learn_policy_signal(
        signal_type="read",
        pattern="接着那条线",
        normalized_intent="continue_thread",
        action="use_memory",
        confidence=0.7,
    )

    promoted = runtime.reinforce_policy_signal(
        signal_type="read",
        pattern="接着那条线",
        action="use_memory",
        supported=True,
    )
    promoted = runtime.reinforce_policy_signal(
        signal_type="read",
        pattern="接着那条线",
        action="use_memory",
        supported=True,
    )
    rejected = runtime.reinforce_policy_signal(
        signal_type="read",
        pattern="接着那条线",
        action="use_memory",
        supported=False,
    )

    assert promoted is not None
    assert promoted.status == "stable"
    assert rejected is not None
    assert rejected.reject_count == 1
    assert runtime.list_policy_signals(signal_type="read", action="use_memory")


def test_retriever_and_reranker_providers_can_be_injected(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")
    first = runtime.capture_memory("我偏好第一种方案。", force=True).memories[0]
    second = runtime.capture_memory("我偏好第二种方案。", force=True).memories[0]
    retriever = StaticRetriever([SearchResult(first, 0.1), SearchResult(second, 0.9)])

    runtime = PersonalMemoryRuntime(
        db_path=tmp_path / "memory.sqlite3",
        policy=AlwaysReadPolicy(),
        retriever=retriever,
        reranker=ReverseReranker(),
    )
    prepared = runtime.prepare_context("按我的偏好继续")

    assert prepared.package is not None
    assert retriever.queries == ["按我的偏好继续"]
    assert [result.memory.id for result in prepared.results] == [second.id, first.id]


def test_consolidator_provider_can_be_injected(tmp_path):
    consolidator = EmptyConsolidator()
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3", consolidator=consolidator)

    result = runtime.consolidate_memory(recent=7)

    assert consolidator.calls == 1
    assert result.memories_scanned == 7


def test_capture_auto_consolidates_after_threshold(tmp_path):
    config = AppConfig(
        consolidation=ConsolidationConfig(
            auto_consolidate=True,
            auto_consolidate_min_memories=2,
        )
    )
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3", config=config)

    runtime.capture_memory(
        """
        [
          {"type": "preference", "content": "用户偏好 self-host 和本地可控系统。"},
          {"type": "style", "content": "用户偏好直接、工程化、可执行的回答。"}
        ]
        """,
        force=True,
    )

    traits = runtime.get_user_profile()
    trait_keys = {trait.trait_key for trait in traits}

    assert "general.preference" in trait_keys
    assert "communication.answer_style" in trait_keys


def test_goal_and_project_memories_consolidate_into_profile_traits(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    runtime.capture_memory("我计划让 PAM-OS 随着交流自动生成长期特征。", force=True)
    runtime.capture_memory("PAM-OS 项目正在实现本地优先的画像记忆系统。", force=True)

    result = runtime.consolidate_memory(recent=100)
    trait_keys = {trait.trait_key for trait in runtime.get_user_profile()}

    assert result.evidence_created
    assert "long_term.goal" in trait_keys
    assert "project.active_context" in trait_keys


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
    assert any(trait.trait_key == "general.decision_style" for trait in traits)


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


def test_storage_stats_include_table_breakdown(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")
    runtime.remember("我偏好 self-host、开源、可控系统。")
    runtime.capture_memory("我决定 Personal AI Memory OS v0.1 先用 SQLite FTS5，不引入 Qdrant。", force=True)
    runtime.record_behavior_choice(
        context="PAM-OS 技术路线",
        chosen=["SQLite FTS5"],
        rejected=["Qdrant"],
        reason="本地轻量可控",
    )

    stats = runtime.get_storage_stats()

    assert stats.db_path.endswith("memory.sqlite3")
    assert stats.db_size_bytes >= 0
    assert "memories" in stats.tables
    assert stats.tables["events"]["count"] >= 1
    assert stats.tables["memories"]["count"] >= 1
    assert "by_type" in stats.tables["memories"]
    assert "behavior_events" in stats.tables
    assert "unconsolidated_count" in stats.tables["behavior_events"]


def test_storage_stats_exposed_by_rest_api(tmp_path):
    app = create_app(db_path=tmp_path / "memory.sqlite3")
    route = next(route for route in app.routes if getattr(route, "path", None) == "/storage/stats")
    payload = route.endpoint()

    assert payload["db_path"].endswith("memory.sqlite3")
    assert "tables" in payload
    assert "memories" in payload["tables"]


def test_inspect_memory_returns_stats_and_details(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")
    runtime.capture_memory("我偏好 self-host、开源、可控系统。", force=True)

    report = runtime.inspect_memory(table="all", limit=10)

    assert "stats" in report
    assert "details" in report
    assert report["stats"]["tables"]["events"]["count"] == 1
    assert report["stats"]["tables"]["memories"]["count"] >= 1
    assert isinstance(report["details"]["events"][0]["metadata"], dict)
    assert report["details"]["memories"][0]["tags"]


def test_inspect_memory_filters_table_rows_by_query(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")
    runtime.capture_memory("我偏好 self-host、开源、可控系统。", force=True)
    runtime.capture_memory("我喜欢安静、直接的工程化回答。", force=True)

    report = runtime.inspect_memory(table="memories", limit=10, query="self-host")

    assert set(report["details"]) == {"memories"}
    assert report["details"]["memories"]
    assert all("self-host" in row["content"] or "self-host" in row["tags"] for row in report["details"]["memories"])


def test_inspect_memory_rejects_unknown_table(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    try:
        runtime.inspect_memory(table="secrets")
    except ValueError as exc:
        assert "table must be one of" in str(exc)
    else:
        raise AssertionError("expected unknown inspect table to be rejected")


def test_inspect_cli_prints_text_report(tmp_path, capsys):
    db_path = tmp_path / "memory.sqlite3"
    runtime = PersonalMemoryRuntime(db_path=db_path)
    runtime.capture_memory("我偏好 self-host、开源、可控系统。", force=True)

    exit_code = main(["--db", str(db_path), "inspect", "--table", "memories", "--limit", "5"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PAM-OS Memory Inspect" in captured.out
    assert "memories" in captured.out
    assert "self-host" in captured.out


def test_inspect_cli_can_output_json_and_filter_rows(tmp_path, capsys):
    db_path = tmp_path / "memory.sqlite3"
    runtime = PersonalMemoryRuntime(db_path=db_path)
    runtime.capture_memory("我偏好 self-host、开源、可控系统。", force=True)
    runtime.capture_memory("我喜欢安静、直接的工程化回答。", force=True)

    exit_code = main(
        [
            "--db",
            str(db_path),
            "inspect",
            "--table",
            "memories",
            "--query",
            "self-host",
            "--json",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert set(payload["details"]) == {"memories"}
    assert payload["details"]["memories"]
    assert all("self-host" in row["content"] or "self-host" in row["tags"] for row in payload["details"]["memories"])


def test_clear_memory_removes_all_stored_memory_data(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")
    runtime.capture_memory("我偏好 self-host、开源、可控系统。", force=True)
    runtime.record_behavior_choice(
        context="PAM-OS 技术路线",
        chosen=["SQLite FTS5"],
        rejected=["Qdrant"],
        reason="本地轻量可控",
    )
    runtime.consolidate_memory(recent=100)
    runtime.compile_context("我继续做 PAM-OS，下一步怎么做？")

    cleared = runtime.clear_memory()
    stats = cleared["storage_stats"]

    assert cleared["deleted_counts"]["events"] >= 1
    assert cleared["deleted_counts"]["memories"] >= 1
    for table_stats in stats.tables.values():
        assert table_stats["count"] == 0
    assert runtime.search_memory("self-host") == []


def test_clear_cli_requires_confirmation(tmp_path, capsys):
    exit_code = main(["--db", str(tmp_path / "memory.sqlite3"), "clear"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "clear requires --confirm" in captured.err


def test_clear_cli_clears_storage(tmp_path, capsys):
    db_path = tmp_path / "memory.sqlite3"
    runtime = PersonalMemoryRuntime(db_path=db_path)
    runtime.capture_memory("我偏好 self-host、开源、可控系统。", force=True)

    exit_code = main(["--db", str(db_path), "clear", "--confirm"])

    captured = capsys.readouterr()
    stats = PersonalMemoryRuntime(db_path=db_path).get_storage_stats()
    assert exit_code == 0
    assert '"deleted_counts"' in captured.out
    assert stats.tables["events"]["count"] == 0
    assert stats.tables["memories"]["count"] == 0



def test_version_cli_outputs_current_version(capsys):
    exit_code = main(["version"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert f"PAM-OS {__version__}" in captured.out


def test_update_check_cli_compares_versions_offline(capsys):
    exit_code = main(["update-check", "--latest-version", "v0.2.1", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["current_version"] == __version__
    assert payload["latest_version"] == "0.2.1"
    assert payload["update_available"] is True


def test_prepare_and_capture_write_quality_traces(tmp_path):
    runtime = PersonalMemoryRuntime(db_path=tmp_path / "memory.sqlite3")

    runtime.capture_memory("我偏好 self-host、开源、可控系统。", force=True)
    runtime.prepare_context("按我的偏好继续做 PAM-OS。", force=True)

    report = runtime.inspect_memory(table="quality_traces", limit=20)
    traces = report["details"]["quality_traces"]
    operations = {trace["operation"] for trace in traces}
    stages = {trace["stage"] for trace in traces}

    assert "capture_memory" in operations
    assert "prepare_context" in operations
    assert {"policy", "extract", "compile"} <= stages
    assert all(trace["trace_id"] for trace in traces)
    assert all(isinstance(trace["metrics"], dict) for trace in traces)


def test_quality_eval_default_cases_pass(capsys):
    exit_code = main(["eval"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PAM-OS Memory Quality Eval" in captured.out
    assert "Failed: 0" in captured.out


def test_quality_eval_json_output(capsys):
    exit_code = main(["eval", "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["failed"] == 0
    assert payload["by_type"]["capture_policy"]["total"] >= 1
