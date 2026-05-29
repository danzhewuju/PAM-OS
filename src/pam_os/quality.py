from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any

from pam_os.config import AppConfig
from pam_os.runtime import PersonalMemoryRuntime
from pam_os.serialization import to_plain


def evaluate_quality_cases(
    paths: list[str | Path] | None = None,
    *,
    config: AppConfig | None = None,
) -> dict[str, Any]:
    cases = load_quality_cases(paths or [default_cases_dir()])
    results = [_evaluate_case(case, config=config) for case in cases]
    return {
        "total": len(results),
        "passed": sum(1 for result in results if result["passed"]),
        "failed": sum(1 for result in results if not result["passed"]),
        "by_type": _summarize_by_type(results),
        "metrics": _quality_metrics(results),
        "results": results,
    }


def default_cases_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "eval" / "cases"


def load_quality_cases(paths: list[str | Path]) -> list[dict[str, Any]]:
    files: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            files.extend(sorted(path.glob("*.json")))
        else:
            files.append(path)

    cases: list[dict[str, Any]] = []
    for path in files:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        items = payload.get("cases", payload) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ValueError(f"quality case file must contain a list or cases object: {path}")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(f"quality case must be an object in {path}")
            item = {**item, "_file": str(path)}
            cases.append(item)
    return cases


def _evaluate_case(case: dict[str, Any], *, config: AppConfig | None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="pam-os-eval-") as tmp_dir:
        runtime = PersonalMemoryRuntime(db_path=Path(tmp_dir) / "memory.sqlite3", config=config)
        _apply_setup(runtime, case.get("setup", {}))
        case_type = case.get("type")
        if case_type == "read_policy":
            return _evaluate_read_policy(runtime, case)
        if case_type == "capture_policy":
            return _evaluate_capture_policy(runtime, case)
        if case_type == "extraction":
            return _evaluate_extraction(runtime, case)
        if case_type == "retrieval":
            return _evaluate_retrieval(runtime, case)
        if case_type == "consolidation":
            return _evaluate_consolidation(runtime, case)
        raise ValueError(f"unknown quality case type: {case_type}")


def _apply_setup(runtime: PersonalMemoryRuntime, setup: dict[str, Any]) -> None:
    for item in setup.get("memories", []):
        if isinstance(item, str):
            runtime.capture_memory(item, force=True)
        elif isinstance(item, dict):
            runtime.remember(json.dumps(item, ensure_ascii=False), source="eval", extract=True)
        else:
            raise ValueError("setup memories must be strings or objects")
    for item in setup.get("behavior_choices", []):
        runtime.record_behavior_choice(**item)


def _evaluate_read_policy(runtime: PersonalMemoryRuntime, case: dict[str, Any]) -> dict[str, Any]:
    expected = case.get("expected", {})
    decision = runtime.should_use_memory(case.get("input", ""), case.get("conversation_summary"))
    checks = [
        _check_equal("should_use", decision.should_use, expected.get("should_use")),
        _check_contains_any("signals_any", decision.signals, expected.get("signals_any", [])),
    ]
    return _case_result(case, checks, actual=to_plain(decision))


def _evaluate_capture_policy(runtime: PersonalMemoryRuntime, case: dict[str, Any]) -> dict[str, Any]:
    expected = case.get("expected", {})
    result = runtime.capture_memory(case.get("input", ""), force=bool(case.get("force", False)))
    memory_types = [memory.type for memory in result.memories]
    memory_content = "\n".join(memory.content for memory in result.memories)
    checks = [
        _check_equal("should_capture", result.should_capture, expected.get("should_capture")),
        _check_contains_all("memory_types", memory_types, expected.get("memory_types", [])),
        _check_text_contains_all("must_include", memory_content, expected.get("must_include", [])),
    ]
    return _case_result(case, checks, actual=to_plain(result))


def _evaluate_extraction(runtime: PersonalMemoryRuntime, case: dict[str, Any]) -> dict[str, Any]:
    expected = case.get("expected", {})
    result = runtime.remember(case.get("input", ""), source="eval", extract=True)
    memories = result["memories"]
    memory_types = [memory.type for memory in memories]
    memory_content = "\n".join(memory.content for memory in memories)
    checks = [
        _check_contains_all("memory_types", memory_types, expected.get("memory_types", [])),
        _check_text_contains_all("must_include", memory_content, expected.get("must_include", [])),
    ]
    return _case_result(case, checks, actual=to_plain(result))


def _evaluate_retrieval(runtime: PersonalMemoryRuntime, case: dict[str, Any]) -> dict[str, Any]:
    expected = case.get("expected", {})
    limit = int(case.get("limit", expected.get("hit_at", 3)))
    results = runtime.search_memory(case.get("query", case.get("input", "")), limit=limit)
    contents = [result.memory.content for result in results]
    combined = "\n".join(contents)
    checks = [_check_text_contains_all("must_retrieve", combined, expected.get("must_retrieve", []))]
    actual = {"results": to_plain(results), "hit_at": limit}
    return _case_result(case, checks, actual=actual)


def _evaluate_consolidation(runtime: PersonalMemoryRuntime, case: dict[str, Any]) -> dict[str, Any]:
    expected = case.get("expected", {})
    result = runtime.consolidate_memory(recent=int(case.get("recent", 100)))
    traits = runtime.get_user_profile(limit=50)
    trait_keys = [trait.trait_key for trait in traits]
    trait_text = "\n".join(trait.statement for trait in traits)
    checks = [
        _check_contains_all("trait_keys", trait_keys, expected.get("trait_keys", [])),
        _check_text_contains_all("must_include", trait_text, expected.get("must_include", [])),
    ]
    return _case_result(case, checks, actual={"result": to_plain(result), "traits": to_plain(traits)})


def _case_result(case: dict[str, Any], checks: list[dict[str, Any]], *, actual: Any) -> dict[str, Any]:
    failures = [check for check in checks if not check["passed"]]
    return {
        "id": case.get("id"),
        "type": case.get("type"),
        "passed": not failures,
        "checks": checks,
        "failures": failures,
        "actual": actual,
        "file": case.get("_file"),
    }


def _check_equal(name: str, actual: Any, expected: Any) -> dict[str, Any]:
    if expected is None:
        return {"name": name, "passed": True, "actual": actual, "expected": expected, "skipped": True}
    return {"name": name, "passed": actual == expected, "actual": actual, "expected": expected}


def _check_contains_all(name: str, actual: list[str], expected: list[str]) -> dict[str, Any]:
    missing = [item for item in expected if item not in actual]
    return {"name": name, "passed": not missing, "actual": actual, "expected": expected, "missing": missing}


def _check_contains_any(name: str, actual: list[str], expected: list[str]) -> dict[str, Any]:
    if not expected:
        return {"name": name, "passed": True, "actual": actual, "expected": expected, "skipped": True}
    matched = [item for item in expected if item in actual]
    return {"name": name, "passed": bool(matched), "actual": actual, "expected": expected, "matched": matched}


def _check_text_contains_all(name: str, actual: str, expected: list[str]) -> dict[str, Any]:
    missing = [item for item in expected if item not in actual]
    return {"name": name, "passed": not missing, "actual": actual, "expected": expected, "missing": missing}


def _summarize_by_type(results: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    summary: dict[str, dict[str, float | int]] = {}
    for result in results:
        item = summary.setdefault(result["type"], {"total": 0, "passed": 0, "failed": 0, "accuracy": 0.0})
        item["total"] += 1
        item["passed"] += 1 if result["passed"] else 0
        item["failed"] += 0 if result["passed"] else 1
    for item in summary.values():
        total = int(item["total"])
        item["accuracy"] = float(item["passed"]) / total if total else 0.0
    return summary


def _quality_metrics(results: list[dict[str, Any]]) -> dict[str, float]:
    total = len(results)
    return {"accuracy": sum(1 for result in results if result["passed"]) / total if total else 0.0}
