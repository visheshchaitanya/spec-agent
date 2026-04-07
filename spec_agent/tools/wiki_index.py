from __future__ import annotations
from pathlib import Path

_HEADER = "# Dev Wiki — Index\n\n| Date | Type | Title | Project | Link |\n|------|------|-------|---------|------|\n"


def update_index(vault_path: str, entry: dict) -> dict:
    """
    Append a row to index.md.

    entry keys: date, type, title, project, path
    path is the relative vault path without .md extension, e.g. "features/auth"

    Returns: {"success": bool}
    """
    index_path = Path(vault_path) / "index.md"

    if not index_path.exists():
        index_path.write_text(_HEADER, encoding="utf-8")

    row = (
        f"| {entry['date']} "
        f"| {entry['type']} "
        f"| {entry['title']} "
        f"| {entry['project']} "
        f"| [[{entry['path']}]] |\n"
    )

    existing = index_path.read_text(encoding="utf-8")
    index_path.write_text(existing + row, encoding="utf-8")
    return {"success": True}
