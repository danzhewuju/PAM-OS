from __future__ import annotations

import json
from pathlib import Path
import tomllib

from pam_os.version import __version__, current_version


ROOT = Path(__file__).resolve().parents[1]


def project_version() -> str:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return pyproject["project"]["version"]


def test_runtime_version_matches_project_metadata():
    expected = project_version()

    assert current_version() == expected
    assert __version__ == expected


def test_plugin_manifest_version_matches_project_metadata():
    manifest = json.loads((ROOT / "plugins/pam-os-memory/.codex-plugin/plugin.json").read_text(encoding="utf-8"))

    assert manifest["version"] == project_version()


def test_uv_lock_project_package_version_matches_project_metadata():
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    package = next(package for package in lock["package"] if package.get("name") == "pam-os")

    assert package["version"] == project_version()


def test_update_examples_do_not_pin_the_current_release_tag():
    current_tag = f"v{project_version()}"

    for path in [ROOT / "README.md", ROOT / "README.zh-CN.md", ROOT / "scripts/update.sh"]:
        assert current_tag not in path.read_text(encoding="utf-8")
