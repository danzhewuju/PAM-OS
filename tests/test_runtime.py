from __future__ import annotations

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
