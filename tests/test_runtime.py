from __future__ import annotations

import json

from pam_os.api import create_app
from pam_os.cli import main
from pam_os.config import load_config
from pam_os.runtime import PersonalMemoryRuntime


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
