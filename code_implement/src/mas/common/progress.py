"""Best-effort stderr progress helpers for long MAS pipeline runs."""

from __future__ import annotations

import os
import sys
from typing import Iterable, TypeVar


T = TypeVar("T")
_quiet = os.environ.get("MAS_PROGRESS_QUIET") == "1"


def set_quiet(value: bool) -> None:
    """Enable or disable all progress output."""

    global _quiet
    try:
        _quiet = bool(value)
        os.environ["MAS_PROGRESS_QUIET"] = "1" if _quiet else "0"
    except Exception:
        pass


def is_quiet() -> bool:
    try:
        return _quiet or os.environ.get("MAS_PROGRESS_QUIET") == "1"
    except Exception:
        return True


def _write(line: str) -> None:
    try:
        if is_quiet():
            return
        print(line, file=sys.stderr, flush=True)
    except Exception:
        pass


def stage_banner(name: str, index: int, total: int) -> None:
    try:
        _write(f"▶ [{index}/{total}] {name} ...")
    except Exception:
        pass


def stage_done(name: str, index: int, total: int, elapsed_seconds: float, extra: str = "") -> None:
    try:
        suffix = f"，{extra}" if extra else ""
        _write(f"✓ [{index}/{total}] {name} 完成（{elapsed_seconds:.1f}s{suffix}）")
    except Exception:
        pass


def stage_failed(name: str, index: int, total: int, error: str) -> None:
    try:
        _write(f"✗ [{index}/{total}] {name} 失败：{error}")
    except Exception:
        pass


def step(msg: str) -> None:
    try:
        _write(f"   · {msg}")
    except Exception:
        pass


def progress_iter(iterable: Iterable[T], desc: str, total: int | None = None) -> Iterable[T]:
    try:
        if is_quiet() or not sys.stderr.isatty():
            return iterable
        from tqdm import tqdm

        return tqdm(iterable, desc=desc, total=total, file=sys.stderr, disable=False)
    except Exception:
        return iterable
