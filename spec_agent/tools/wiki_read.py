from __future__ import annotations
from pathlib import Path
import frontmatter


def read_wiki_file(vault_path: str, relative_path: str) -> dict:
    """
    Read a markdown file from the vault.

    Returns:
        {
            "exists": bool,
            "content": str,          # body text without frontmatter
            "frontmatter": dict,     # parsed YAML frontmatter (empty if none)
            "last_updated": str,     # ISO date from frontmatter or ""
        }
    """
    full_path = (Path(vault_path) / relative_path).resolve()
    vault_resolved = Path(vault_path).resolve()
    if not str(full_path).startswith(str(vault_resolved) + "/") and full_path != vault_resolved:
        return {"success": False, "path": relative_path, "content": None, "error": "Path traversal rejected"}
    if not full_path.exists():
        return {"exists": False, "content": "", "frontmatter": {}, "last_updated": ""}

    raw = full_path.read_text(encoding="utf-8")

    try:
        post = frontmatter.loads(raw)
        meta = dict(post.metadata)
        body = post.content
    except Exception:
        meta = {}
        body = raw

    return {
        "exists": True,
        "content": body,
        "frontmatter": meta,
        "last_updated": str(meta.get("date", "")),
    }
