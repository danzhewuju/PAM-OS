from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

__version__ = "0.4.2"
DEFAULT_REPOSITORY = "danzhewuju/PAM-OS"
GITHUB_API = "https://api.github.com"


@dataclass(frozen=True)
class UpdateStatus:
    current_version: str
    latest_version: str | None
    update_available: bool
    release_url: str | None = None
    error: str | None = None


def current_version() -> str:
    return __version__


def check_for_updates(
    *,
    current: str | None = None,
    latest: str | None = None,
    repository: str = DEFAULT_REPOSITORY,
    timeout: float = 5.0,
) -> UpdateStatus:
    current = normalize_version(current or __version__)
    release_url = None
    error = None
    if latest is None:
        try:
            payload = fetch_latest_release(repository=repository, timeout=timeout)
            latest = str(payload.get("tag_name") or payload.get("name") or "").strip()
            release_url = payload.get("html_url")
        except Exception as exc:  # pragma: no cover - network behavior varies by host.
            error = str(exc)
    latest_version = normalize_version(latest) if latest else None
    return UpdateStatus(
        current_version=current,
        latest_version=latest_version,
        update_available=bool(latest_version and compare_versions(latest_version, current) > 0),
        release_url=release_url,
        error=error,
    )


def fetch_latest_release(*, repository: str, timeout: float = 5.0) -> dict[str, Any]:
    url = f"{GITHUB_API}/repos/{repository}/releases/latest"
    request = Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "pam-os-update-check"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except URLError as exc:
        raise RuntimeError(f"could not reach GitHub releases API: {exc.reason}") from exc


def normalize_version(version: str) -> str:
    version = version.strip()
    return version[1:] if version.startswith("v") else version


def compare_versions(left: str, right: str) -> int:
    left_parts = version_parts(left)
    right_parts = version_parts(right)
    width = max(len(left_parts), len(right_parts))
    left_parts.extend([0] * (width - len(left_parts)))
    right_parts.extend([0] * (width - len(right_parts)))
    return (left_parts > right_parts) - (left_parts < right_parts)


def version_parts(version: str) -> list[int]:
    core = normalize_version(version).split("-", maxsplit=1)[0]
    parts = [int(part) for part in re.findall(r"\d+", core)]
    return parts or [0]
