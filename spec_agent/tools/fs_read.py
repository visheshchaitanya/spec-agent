"""Filesystem read tools for the init-repo agent."""
from __future__ import annotations
import fnmatch
import os
from pathlib import Path

_SKIP_DIRS: frozenset[str] = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "target", "build", "dist", ".gradle", ".idea",
    ".pytest_cache", ".mypy_cache", ".tox", ".eggs",
    "coverage", ".coverage",
})
_SKIP_EXTENSIONS: frozenset[str] = frozenset({
    ".pyc", ".pyo", ".class", ".jar", ".war", ".ear",
    ".min.js", ".map", ".wasm",
})
_SKIP_FILES: frozenset[str] = frozenset({
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "poetry.lock", "Pipfile.lock", "Cargo.lock", "go.sum",
    "composer.lock",
})
_MAX_TREE_CHARS = 6_000


def _load_gitignore_patterns(repo_path: str) -> list[str]:
    gitignore = Path(repo_path) / ".gitignore"
    if not gitignore.exists():
        return []
    patterns: list[str] = []
    for line in gitignore.read_text(errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            patterns.append(line.rstrip("/"))
    return patterns


def list_directory(
    repo_path: str,
    relative_path: str = ".",
    max_depth: int = 3,
) -> dict:
    """Return a directory tree string, skipping generated/vendor paths."""
    root = Path(repo_path) / relative_path
    if not root.exists():
        return {"error": f"Path does not exist: {relative_path}"}

    gitignore_patterns = _load_gitignore_patterns(repo_path)
    lines: list[str] = []

    def _is_gitignored(name: str) -> bool:
        for pattern in gitignore_patterns:
            if fnmatch.fnmatch(name, pattern):
                return True
        return False

    def _is_dir_skipped(name: str) -> bool:
        if name in _SKIP_DIRS:
            return True
        return _is_gitignored(name)

    def _walk(path: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return

        visible = [e for e in entries if not (e.is_dir() and _is_dir_skipped(e.name))]
        for i, entry in enumerate(visible):
            if entry.is_file():
                if entry.suffix in _SKIP_EXTENSIONS or entry.name in _SKIP_FILES:
                    continue
                if _is_gitignored(entry.name):
                    continue
            connector = "└── " if i == len(visible) - 1 else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")
            if entry.is_dir():
                extension = "    " if i == len(visible) - 1 else "│   "
                _walk(entry, prefix + extension, depth + 1)

    _walk(root, "", 0)
    tree = "\n".join(lines)

    if len(tree) > _MAX_TREE_CHARS:
        tree = tree[:_MAX_TREE_CHARS] + f"\n... (truncated, {len(lines)} total entries)"

    return {"tree": tree, "root": str(relative_path)}


def read_source_file(
    repo_path: str,
    relative_path: str,
    max_chars: int = 8_000,
) -> dict:
    """Read a source file from the repo with a character cap."""
    path = Path(repo_path) / relative_path
    if not path.exists():
        return {"error": f"File not found: {relative_path}"}
    if not path.is_file():
        return {"error": f"Not a file: {relative_path}"}
    if path.suffix in _SKIP_EXTENSIONS:
        return {"error": f"Binary/generated file skipped: {relative_path}"}
    if path.name in _SKIP_FILES:
        return {"error": f"Generated/lock file skipped: {relative_path}"}

    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"error": f"Could not read {relative_path}: {exc}"}

    truncated = len(content) > max_chars
    return {
        "path": relative_path,
        "content": content[:max_chars],
        "truncated": truncated,
        "total_chars": len(content),
    }
