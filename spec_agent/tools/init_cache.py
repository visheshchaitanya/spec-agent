"""File-timestamp cache for init-repo re-run detection."""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from spec_agent.tools.fs_read import _SKIP_DIRS, _SKIP_EXTENSIONS, _SKIP_FILES

_CACHE_DIR = Path.home() / ".spec-agent" / "cache"

# Additional dirs to skip when walking a repo (spec-agent internal dirs)
_EXTRA_SKIP_DIRS: frozenset[str] = frozenset({".spec-agent"})


def _cache_path(repo_name: str) -> Path:
    return _CACHE_DIR / f"{repo_name}.json"


def load_cache(repo_name: str) -> dict:
    """Load the cache for a repo. Returns empty dict if missing or corrupt."""
    path = _cache_path(repo_name)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_cache(repo_name: str, repo_path: str) -> None:
    """Snapshot current file mtimes for the repo."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    files: dict[str, float] = {}
    root = Path(repo_path)

    _all_skip_dirs = _SKIP_DIRS | _EXTRA_SKIP_DIRS
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _all_skip_dirs]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix in _SKIP_EXTENSIONS or fname in _SKIP_FILES:
                continue
            rel = str(fpath.relative_to(root))
            try:
                files[rel] = fpath.stat().st_mtime
            except OSError:
                pass

    data = {
        "last_run": datetime.now(timezone.utc).isoformat(),
        "files": files,
    }
    _cache_path(repo_name).write_text(json.dumps(data, indent=2))


def get_changed_files(repo_path: str, repo_name: str) -> list[str]:
    """Return files changed or added since the last cache snapshot.

    Returns empty list if no cache exists (first run).
    """
    cache = load_cache(repo_name)
    if not cache:
        return []

    cached_files: dict[str, float] = cache.get("files", {})
    changed: list[str] = []
    root = Path(repo_path)

    # Detect modified files
    for rel_path, old_mtime in cached_files.items():
        fpath = root / rel_path
        try:
            if fpath.stat().st_mtime != old_mtime:
                changed.append(rel_path)
        except FileNotFoundError:
            pass  # deleted files not surfaced as "changed"

    # Detect new files
    _all_skip_dirs = _SKIP_DIRS | _EXTRA_SKIP_DIRS
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _all_skip_dirs]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix in _SKIP_EXTENSIONS or fname in _SKIP_FILES:
                continue
            rel = str(fpath.relative_to(root))
            if rel not in cached_files:
                changed.append(rel)

    return changed
