from __future__ import annotations

from pathlib import Path
import re
import subprocess


PROJECT_ROOT = Path(__file__).resolve().parents[3]
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".txt",
    ".vue",
    ".yaml",
    ".yml",
}
SKIPPED_PARTS = {
    ".git",
    ".venv",
    "node_modules",
    "web/storage",
}
SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{20,}\b"),
    re.compile(r"https://[A-Za-z0-9-]+\.trycloudflare\.com\b"),
    re.compile(r"https://[A-Za-z0-9.-]+\.ngrok(?:-free)?\.app\b"),
    re.compile(r"FAMAS_SECRET_KEY\s*=\s*['\"](?!<)[^'\"]{16,}['\"]"),
    re.compile(r"FAMAS_ADMIN_PASSWORD\s*=\s*['\"](?!<)[^'\"]{6,}['\"]"),
]


def test_tracked_files_do_not_contain_obvious_secrets() -> None:
    failures: list[str] = []
    for path in _tracked_text_files():
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                failures.append(f"{path.relative_to(PROJECT_ROOT)} matched {pattern.pattern}")

    assert failures == []


def _tracked_text_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        path = PROJECT_ROOT / line
        normalized = line.replace("\\", "/")
        if any(part in normalized for part in SKIPPED_PARTS):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if path.name in {"package-lock.json"}:
            continue
        paths.append(path)
    return paths
