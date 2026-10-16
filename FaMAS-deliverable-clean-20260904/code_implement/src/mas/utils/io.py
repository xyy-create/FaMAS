"""Small file I/O helpers shared by MAS pipeline stages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Union


def write_json(path: Union[str, Path], obj: Any, *, indent: int = 2) -> None:
    """Write JSON with UTF-8 encoding and create parent directories."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(obj, handle, ensure_ascii=False, indent=indent)
        handle.write("\n")
