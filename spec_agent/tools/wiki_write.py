from __future__ import annotations
from pathlib import Path


def write_wiki_file(vault_path: str, relative_path: str, content: str, mode: str = "create") -> dict:
    """
    Write a markdown file to the vault.

    Args:
        vault_path: Absolute path to the Obsidian vault directory.
        relative_path: Path relative to vault root, e.g. "features/auth.md".
        content: In create mode: full file content. In update mode: changelog line(s) to append.
        mode: "create" (overwrite) or "update" (append changelog entry).

    Returns:
        {"success": bool, "path": str, "error": str | None}
    """
    full_path = (Path(vault_path) / relative_path).resolve()
    vault_resolved = Path(vault_path).resolve()
    if not str(full_path).startswith(str(vault_resolved) + "/") and full_path != vault_resolved:
        return {"success": False, "path": relative_path, "error": "Path traversal rejected"}
    full_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if mode == "create":
            full_path.write_text(content, encoding="utf-8")
        elif mode == "update":
            existing = full_path.read_text(encoding="utf-8") if full_path.exists() else ""
            if "## Changelog" in existing:
                # Append after the last changelog entry
                updated = existing.rstrip() + "\n" + content + "\n"
            else:
                # Add a Changelog section
                updated = existing.rstrip() + "\n\n## Changelog\n\n" + content + "\n"
            full_path.write_text(updated, encoding="utf-8")
        else:
            return {"success": False, "path": relative_path, "error": f"Unknown mode: {mode}"}

        return {"success": True, "path": relative_path, "error": None}
    except Exception as e:
        return {"success": False, "path": relative_path, "error": str(e)}
