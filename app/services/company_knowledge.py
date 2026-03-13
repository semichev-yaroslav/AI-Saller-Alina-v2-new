from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_ALLOWED_SUFFIXES = {".md", ".txt"}


def load_company_knowledge(
    *,
    directory: str,
    max_files: int,
    max_chars: int,
) -> list[dict[str, str]]:
    root = Path(directory)
    if not root.is_absolute():
        root = _PROJECT_ROOT / root

    if not root.exists() or not root.is_dir():
        return []

    docs: list[dict[str, str]] = []
    files = sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in _ALLOWED_SUFFIXES)

    for path in files[:max_files]:
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError:
            logger.warning("Failed to read company knowledge file", extra={"path": str(path)})
            continue

        if not content:
            continue

        try:
            display_path = str(path.relative_to(_PROJECT_ROOT))
        except ValueError:
            display_path = str(path)

        docs.append(
            {
                "title": path.stem,
                "path": display_path,
                "content": content[:max_chars],
            }
        )

    return docs
