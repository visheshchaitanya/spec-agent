from __future__ import annotations
from pathlib import Path

_HEADER = "# Dev Wiki — Index\n\n| Date | Type | Title | Project | Link |\n|------|------|-------|---------|------|\n"


def _sanitize(value: str) -> str:
    return str(value).replace("|", "").replace("\n", " ").replace("\r", "").strip()


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
        f"| {_sanitize(entry['date'])} "
        f"| {_sanitize(entry['type'])} "
        f"| {_sanitize(entry['title'])} "
        f"| {_sanitize(entry['project'])} "
        f"| [[{_sanitize(entry['path'])}]] |\n"
    )

    try:
        existing = index_path.read_text(encoding="utf-8")
        index_path.write_text(existing + row, encoding="utf-8")
        return {"success": True, "path": str(index_path)}
    except OSError as e:
        return {"success": False, "error": str(e)}
