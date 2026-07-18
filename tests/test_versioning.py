from __future__ import annotations

import json
import os
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


def test_packaged_skill_configs_identify_skill_and_api_versions():
    paths = [
        ROOT / "skills/pam-os-memory/config.toml",
        ROOT / "plugins/pam-os-memory/skills/pam-os-memory/config.toml",
    ]

    for path in paths:
        versions = tomllib.loads(path.read_text(encoding="utf-8"))["versions"]
        assert versions["skill"] == project_version()
        assert versions["api"] == "v1"
        assert versions["status"] == "not_checked"


def test_packaged_skill_docs_show_current_config_version():
    expected = f'skill = "{project_version()}"'
    paths = [
        ROOT / "skills/pam-os-memory/SKILL.md",
        ROOT / "plugins/pam-os-memory/skills/pam-os-memory/SKILL.md",
    ]

    for path in paths:
        assert expected in path.read_text(encoding="utf-8")


def test_install_examples_do_not_pin_the_current_release_tag():
    current_tag = f"v{project_version()}"

    for path in [ROOT / "README.md", ROOT / "README.zh-CN.md", ROOT / "scripts/install.sh", ROOT / "scripts/install.ps1"]:
        assert current_tag not in path.read_text(encoding="utf-8")


def test_scripts_directory_contains_only_platform_installers():
    scripts = sorted(path.name for path in (ROOT / "scripts").iterdir() if path.is_file())

    assert scripts == ["install.ps1", "install.sh"]
    if os.name != "nt":
        assert os.access(ROOT / "scripts/install.sh", os.X_OK)
