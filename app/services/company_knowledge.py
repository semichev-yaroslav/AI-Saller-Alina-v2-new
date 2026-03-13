from __future__ import annotations

import logging
from pathlib import Path
import re

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


def retrieve_company_knowledge(
    *,
    query: str,
    documents: list[dict[str, str]],
    limit: int = 4,
) -> list[dict[str, str]]:
    query_tokens = _tokenize(query)
    if not documents:
        return []
    if not query_tokens:
        return documents[:limit]

    ranked: list[tuple[int, dict[str, str]]] = []
    for doc in documents:
        haystack = " ".join([str(doc.get("title") or ""), str(doc.get("content") or "")])
        haystack_tokens = _tokenize(haystack)
        score = sum(1 for token in query_tokens if token in haystack_tokens)
        if score <= 0:
            continue
        ranked.append((score, doc))

    ranked.sort(key=lambda item: item[0], reverse=True)
    if ranked:
        return [doc for _, doc in ranked[:limit]]
    return documents[:limit]


def _tokenize(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[A-Za-zА-Яа-я0-9]{3,}", text.lower())
        if token not in {"это", "как", "что", "для", "или", "при", "the", "and"}
    }
