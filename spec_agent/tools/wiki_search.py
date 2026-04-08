from __future__ import annotations
import subprocess
import shutil
from pathlib import Path


def _find_grep() -> str:
    """Return path to system grep binary."""
    for candidate in ("ggrep", "grep"):
        found = shutil.which(candidate)
        if found:
            return found
    return "grep"  # last resort, subprocess will raise clearly if missing


def search_wiki(vault_path: str, query: str, limit: int = 5) -> list[dict]:
    """
    Full-text search across the vault using grep.

    Returns:
        [{"path": str, "title": str, "excerpt": str}]
        path is relative to vault root.
    """
    vault = Path(vault_path)
    results = []
    seen_files: set[str] = set()

    grep = _find_grep()
    query = query.strip()[:500]
    # -r recursive, -i case-insensitive, -n line numbers, --include only .md
    # Output format: /path/file.md:linenum:matching line
    # -- separates options from the query to prevent flag injection
    cmd = [grep, "-r", "-i", "-n", "--include=*.md", "--", query, str(vault)]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    for line in proc.stdout.splitlines():
        if len(results) >= limit:
            break

        # Parse: /path/to/file.md:line_num:matching line
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        file_path, _, excerpt = parts

        file_path = file_path.strip()
        if file_path in seen_files or not file_path.endswith(".md"):
            continue
        seen_files.add(file_path)

        try:
            rel_path = str(Path(file_path).relative_to(vault))
        except ValueError:
            continue

        # Read first heading as title
        try:
            first_line = Path(file_path).read_text(encoding="utf-8").splitlines()[0]
            title = first_line.lstrip("#").strip() if first_line.startswith("#") else rel_path
        except Exception:
            title = rel_path

        results.append({
            "path": rel_path,
            "title": title,
            "excerpt": excerpt.strip()[:200],
        })

    return results
