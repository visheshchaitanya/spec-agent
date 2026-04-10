# init-repo & opt-out/opt-in Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `spec-agent init-repo` to bootstrap a knowledge base from an existing codebase, and `spec-agent opt-out` / `spec-agent opt-in` to exclude repos from the global hook.

**Architecture:** A new `init_agent.py` (mirrors `agent.py`) uses a tool-use loop with two new filesystem tools (`list_directory`, `read_source_file`) plus the existing vault-write tools to explore a repo and write KB docs under `projects/<service-name>/`. A lightweight file-timestamp cache (`init_cache.py`) makes `--force` re-runs efficient. Two new CLI commands (`opt-out`, `opt-in`) wire into the already-present `Config.ignored_repos` field.

**Tech Stack:** Python 3.10+, Click, pytest, PyYAML, pathlib (stdlib). No new dependencies required.

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `spec_agent/tools/fs_read.py` | `list_directory` + `read_source_file` tools |
| Create | `spec_agent/tools/init_cache.py` | File-timestamp cache (save / load / diff) |
| Create | `spec_agent/init_agent.py` | Init agent loop, tool definitions, system prompt |
| Modify | `spec_agent/cli.py` | Add `init-repo`, `opt-out`, `opt-in` commands |
| Create | `tests/test_fs_read.py` | Unit tests for filesystem tools |
| Create | `tests/test_init_cache.py` | Unit tests for cache |
| Create | `tests/test_init_agent.py` | Unit tests for init agent loop |
| Modify | `tests/test_cli.py` | Tests for new CLI commands |

---

## Task 1: Filesystem Tools — `spec_agent/tools/fs_read.py`

**Files:**
- Create: `spec_agent/tools/fs_read.py`
- Test: `tests/test_fs_read.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fs_read.py`:

```python
"""Tests for filesystem read tools."""
from __future__ import annotations
from pathlib import Path
import pytest
from spec_agent.tools.fs_read import list_directory, read_source_file


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A minimal fake repo directory."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main(): pass\n")
    (tmp_path / "src" / "utils.py").write_text("def helper(): return 42\n")
    (tmp_path / "README.md").write_text("# My Service\n\nDoes things.\n")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lodash").mkdir()
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "requirements.txt").write_text("click\n")
    return tmp_path


class TestListDirectory:
    def test_returns_tree_string(self, repo: Path) -> None:
        result = list_directory(str(repo))
        assert "tree" in result
        assert isinstance(result["tree"], str)

    def test_includes_source_files(self, repo: Path) -> None:
        result = list_directory(str(repo))
        assert "main.py" in result["tree"]
        assert "README.md" in result["tree"]

    def test_skips_git_dir(self, repo: Path) -> None:
        result = list_directory(str(repo))
        assert ".git" not in result["tree"]

    def test_skips_node_modules(self, repo: Path) -> None:
        result = list_directory(str(repo))
        assert "node_modules" not in result["tree"]

    def test_skips_pycache(self, repo: Path) -> None:
        result = list_directory(str(repo))
        assert "__pycache__" not in result["tree"]

    def test_subdirectory_path(self, repo: Path) -> None:
        result = list_directory(str(repo), relative_path="src")
        assert "main.py" in result["tree"]

    def test_nonexistent_path_returns_error(self, repo: Path) -> None:
        result = list_directory(str(repo), relative_path="nonexistent")
        assert "error" in result

    def test_max_depth_limits_output(self, repo: Path) -> None:
        deep = repo / "a" / "b" / "c" / "d"
        deep.mkdir(parents=True)
        (deep / "deep.py").write_text("x = 1")
        result = list_directory(str(repo), max_depth=2)
        assert "deep.py" not in result["tree"]

    def test_respects_gitignore(self, repo: Path) -> None:
        (repo / ".gitignore").write_text("*.log\nbuild/\n")
        (repo / "app.log").write_text("log content")
        (repo / "build").mkdir()
        (repo / "build" / "output.js").write_text("compiled")
        result = list_directory(str(repo))
        assert "app.log" not in result["tree"]
        assert "build" not in result["tree"]


class TestReadSourceFile:
    def test_reads_file_content(self, repo: Path) -> None:
        result = read_source_file(str(repo), "README.md")
        assert result["content"] == "# My Service\n\nDoes things.\n"
        assert result["truncated"] is False

    def test_truncates_large_files(self, repo: Path) -> None:
        large = repo / "big.py"
        large.write_text("x" * 10_000)
        result = read_source_file(str(repo), "big.py", max_chars=100)
        assert len(result["content"]) == 100
        assert result["truncated"] is True
        assert result["total_chars"] == 10_000

    def test_file_not_found_returns_error(self, repo: Path) -> None:
        result = read_source_file(str(repo), "nonexistent.py")
        assert "error" in result

    def test_skips_pyc_files(self, repo: Path) -> None:
        (repo / "compiled.pyc").write_bytes(b"\x00\x01\x02")
        result = read_source_file(str(repo), "compiled.pyc")
        assert "error" in result

    def test_reads_nested_file(self, repo: Path) -> None:
        result = read_source_file(str(repo), "src/main.py")
        assert "def main" in result["content"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/vishesh/Documents/Personal/spec-agent
pytest tests/test_fs_read.py -v 2>&1 | head -30
```

Expected: `ImportError` or `ModuleNotFoundError` — `fs_read` does not exist yet.

- [ ] **Step 3: Implement `spec_agent/tools/fs_read.py`**

```python
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
            # Strip trailing slashes for directory patterns
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

    def _is_ignored(name: str) -> bool:
        if name in _SKIP_DIRS:
            return True
        for pattern in gitignore_patterns:
            if fnmatch.fnmatch(name, pattern):
                return True
        return False

    def _walk(path: Path, prefix: str, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return

        visible = [e for e in entries if not (e.is_dir() and _is_ignored(e.name))]
        for i, entry in enumerate(visible):
            if entry.is_file():
                if entry.suffix in _SKIP_EXTENSIONS or entry.name in _SKIP_FILES:
                    continue
            connector = "└── " if i == len(visible) - 1 else "├── "
            lines.append(f"{prefix}{connector}{entry.name}")
            if entry.is_dir():
                extension = "    " if i == len(visible) - 1 else "│   "
                _walk(entry, prefix + extension, depth + 1)

    _walk(root, "", 0)
    tree = "\n".join(lines)

    # Guard against overwhelming the LLM with a massive tree
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_fs_read.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add spec_agent/tools/fs_read.py tests/test_fs_read.py
git commit -m "feat: add list_directory and read_source_file tools for init-repo"
```

---

## Task 2: Init Cache — `spec_agent/tools/init_cache.py`

**Files:**
- Create: `spec_agent/tools/init_cache.py`
- Test: `tests/test_init_cache.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_init_cache.py`:

```python
"""Tests for init-repo file-timestamp cache."""
from __future__ import annotations
import json
import time
from pathlib import Path
import pytest
from spec_agent.tools.init_cache import load_cache, save_cache, get_changed_files


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1")
    (tmp_path / "README.md").write_text("hello")
    return tmp_path


@pytest.fixture
def cache_dir(tmp_path: Path, monkeypatch) -> Path:
    """Redirect cache writes to tmp_path."""
    cache_root = tmp_path / ".spec-agent" / "cache"
    monkeypatch.setattr(
        "spec_agent.tools.init_cache._CACHE_DIR", cache_root
    )
    return cache_root


class TestLoadCache:
    def test_returns_empty_dict_when_missing(self, cache_dir: Path) -> None:
        result = load_cache("nonexistent-repo")
        assert result == {}

    def test_returns_empty_dict_on_corrupt_json(self, cache_dir: Path) -> None:
        cache_dir.mkdir(parents=True)
        (cache_dir / "bad-repo.json").write_text("not json {{{")
        result = load_cache("bad-repo")
        assert result == {}


class TestSaveAndLoadCache:
    def test_roundtrip(self, repo: Path, cache_dir: Path) -> None:
        save_cache("my-service", str(repo))
        loaded = load_cache("my-service")
        assert "last_run" in loaded
        assert "files" in loaded
        # Both source files should be in cache
        files = loaded["files"]
        assert any("app.py" in k for k in files)
        assert any("README.md" in k for k in files)

    def test_skips_pyc_files(self, repo: Path, cache_dir: Path) -> None:
        (repo / "compiled.pyc").write_bytes(b"\x00\x01")
        save_cache("my-service", str(repo))
        loaded = load_cache("my-service")
        assert not any(".pyc" in k for k in loaded["files"])


class TestGetChangedFiles:
    def test_returns_empty_when_no_cache(self, repo: Path, cache_dir: Path) -> None:
        result = get_changed_files(str(repo), "fresh-repo")
        assert result == []

    def test_detects_modified_file(self, repo: Path, cache_dir: Path) -> None:
        save_cache("my-service", str(repo))
        # Wait a moment and modify a file (change mtime)
        app_py = repo / "src" / "app.py"
        time.sleep(0.01)
        app_py.write_text("x = 2")
        changed = get_changed_files(str(repo), "my-service")
        assert any("app.py" in f for f in changed)

    def test_detects_new_file(self, repo: Path, cache_dir: Path) -> None:
        save_cache("my-service", str(repo))
        (repo / "src" / "new_module.py").write_text("y = 99")
        changed = get_changed_files(str(repo), "my-service")
        assert any("new_module.py" in f for f in changed)

    def test_unchanged_files_not_returned(self, repo: Path, cache_dir: Path) -> None:
        save_cache("my-service", str(repo))
        changed = get_changed_files(str(repo), "my-service")
        assert changed == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_init_cache.py -v 2>&1 | head -20
```

Expected: `ImportError` — `init_cache` does not exist yet.

- [ ] **Step 3: Implement `spec_agent/tools/init_cache.py`**

```python
"""File-timestamp cache for init-repo re-run detection."""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from spec_agent.tools.fs_read import _SKIP_DIRS, _SKIP_EXTENSIONS, _SKIP_FILES

_CACHE_DIR = Path.home() / ".spec-agent" / "cache"


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

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
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
            pass  # deleted files are not surfaced as "changed"

    # Detect new files
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            if fpath.suffix in _SKIP_EXTENSIONS or fname in _SKIP_FILES:
                continue
            rel = str(fpath.relative_to(root))
            if rel not in cached_files:
                changed.append(rel)

    return changed
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_init_cache.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add spec_agent/tools/init_cache.py tests/test_init_cache.py
git commit -m "feat: add file-timestamp cache for init-repo re-run detection"
```

---

## Task 3: Init Agent — `spec_agent/init_agent.py`

**Files:**
- Create: `spec_agent/init_agent.py`
- Test: `tests/test_init_agent.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_init_agent.py`:

```python
"""Tests for the init-repo agent loop."""
from __future__ import annotations
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from spec_agent.init_agent import run_init_agent, _MAX_ITERATIONS
from spec_agent.config import Config
from spec_agent.backends.base import ChatResponse, ToolCall


@pytest.fixture
def cfg(vault_dir: Path) -> Config:
    return Config(vault_path=vault_dir)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "README.md").write_text("# My Service\nDoes payments.")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("def main(): pass")
    return tmp_path


def _end_turn(text: str = "Done.") -> ChatResponse:
    return ChatResponse(
        stop_reason="end_turn",
        text=text,
        tool_calls=[],
        raw_assistant_turn={"role": "assistant", "content": text},
    )


def _tool_use(name: str, arguments: dict, tool_id: str = "t1") -> ChatResponse:
    tc = ToolCall(id=tool_id, name=name, arguments=arguments)
    return ChatResponse(
        stop_reason="tool_use",
        text=None,
        tool_calls=[tc],
        raw_assistant_turn={"role": "assistant", "content": None},
    )


class TestRunInitAgent:
    def test_writes_overview_doc(self, cfg: Config, vault_dir: Path, repo: Path) -> None:
        """Agent can write a KB overview doc via write_wiki_file tool."""
        call_count = 0

        def fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _tool_use("list_directory", {"relative_path": "."})
            if call_count == 2:
                return _tool_use("write_wiki_file", {
                    "path": "projects/my-service/overview.md",
                    "content": "---\ntype: kb-component\nproject: my-service\ndate: 2026-04-10\n---\n# my-service overview\n\n## Purpose\nPayments.\n\n## Keywords\npayments, main\n",
                    "mode": "create",
                })
            if call_count == 3:
                return _tool_use("update_index", {
                    "date": "2026-04-10", "type": "project",
                    "title": "my-service KB", "project": "my-service",
                    "path": "projects/my-service/overview",
                })
            return _end_turn()

        mock_backend = MagicMock()
        mock_backend.chat.side_effect = fake_chat
        mock_backend.make_user_message.side_effect = lambda c: {"role": "user", "content": c}
        mock_backend.make_tool_results_messages.return_value = [{"role": "tool", "content": "ok"}]

        with patch("spec_agent.init_agent.get_backend", return_value=mock_backend):
            run_init_agent(
                repo_path=str(repo),
                repo_name="my-service",
                cfg=cfg,
            )

        assert (vault_dir / "projects" / "my-service" / "overview.md").exists()
        assert "my-service KB" in (vault_dir / "index.md").read_text()

    def test_dispatches_list_directory(self, cfg: Config, repo: Path) -> None:
        """list_directory tool call returns tree output."""
        captured_result = {}

        def fake_chat(**kwargs):
            return _end_turn()

        def fake_tool_results(tool_calls, results):
            if tool_calls and tool_calls[0].name == "list_directory":
                captured_result["tree"] = results[0]
            return [{"role": "tool", "content": r} for r in results]

        call_count = 0

        def fake_chat2(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _tool_use("list_directory", {"relative_path": "."})
            return _end_turn()

        mock_backend = MagicMock()
        mock_backend.chat.side_effect = fake_chat2
        mock_backend.make_user_message.side_effect = lambda c: {"role": "user", "content": c}
        mock_backend.make_tool_results_messages.side_effect = fake_tool_results

        with patch("spec_agent.init_agent.get_backend", return_value=mock_backend):
            run_init_agent(repo_path=str(repo), repo_name="my-service", cfg=cfg)

        assert "tree" in captured_result
        import json
        tree_data = json.loads(captured_result["tree"])
        assert "README.md" in tree_data.get("tree", "")

    def test_dispatches_read_source_file(self, cfg: Config, repo: Path) -> None:
        """read_source_file tool call returns file content."""
        call_count = 0

        def fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _tool_use("read_source_file", {"path": "README.md"})
            return _end_turn()

        mock_backend = MagicMock()
        mock_backend.chat.side_effect = fake_chat
        mock_backend.make_user_message.side_effect = lambda c: {"role": "user", "content": c}

        results_seen = []
        def capture(tool_calls, results):
            results_seen.extend(results)
            return [{"role": "tool", "content": r} for r in results]

        mock_backend.make_tool_results_messages.side_effect = capture

        with patch("spec_agent.init_agent.get_backend", return_value=mock_backend):
            run_init_agent(repo_path=str(repo), repo_name="my-service", cfg=cfg)

        import json
        result = json.loads(results_seen[0])
        assert "My Service" in result.get("content", "")

    def test_respects_max_iterations(self, cfg: Config, repo: Path) -> None:
        """Agent halts after _MAX_ITERATIONS even if always returning tool_use."""
        mock_backend = MagicMock()
        mock_backend.chat.return_value = _tool_use("list_directory", {})
        mock_backend.make_user_message.side_effect = lambda c: {"role": "user", "content": c}
        mock_backend.make_tool_results_messages.return_value = [{"role": "tool", "content": '{"tree": ""}'}]

        with patch("spec_agent.init_agent.get_backend", return_value=mock_backend):
            run_init_agent(repo_path=str(repo), repo_name="my-service", cfg=cfg)

        assert mock_backend.chat.call_count == _MAX_ITERATIONS

    def test_deep_mode_uses_different_prompt(self, cfg: Config, repo: Path) -> None:
        """--deep mode passes a different system prompt."""
        prompts_seen = []

        def fake_chat(**kwargs):
            prompts_seen.append(kwargs.get("system", ""))
            return _end_turn()

        mock_backend = MagicMock()
        mock_backend.chat.side_effect = fake_chat
        mock_backend.make_user_message.side_effect = lambda c: {"role": "user", "content": c}

        with patch("spec_agent.init_agent.get_backend", return_value=mock_backend):
            run_init_agent(repo_path=str(repo), repo_name="my-service", cfg=cfg, deep=True)

        assert prompts_seen
        assert "deep" in prompts_seen[0].lower()

    def test_changed_files_appear_in_user_message(self, cfg: Config, repo: Path) -> None:
        """On --force re-run, changed files are listed in the user message."""
        messages_seen = []

        def fake_make_user_message(content):
            messages_seen.append(content)
            return {"role": "user", "content": content}

        mock_backend = MagicMock()
        mock_backend.chat.return_value = _end_turn()
        mock_backend.make_user_message.side_effect = fake_make_user_message

        with patch("spec_agent.init_agent.get_backend", return_value=mock_backend):
            run_init_agent(
                repo_path=str(repo),
                repo_name="my-service",
                cfg=cfg,
                changed_files=["src/app.py", "src/new_module.py"],
            )

        assert messages_seen
        assert "src/app.py" in messages_seen[0]
        assert "src/new_module.py" in messages_seen[0]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_init_agent.py -v 2>&1 | head -20
```

Expected: `ImportError` — `init_agent` does not exist yet.

- [ ] **Step 3: Implement `spec_agent/init_agent.py`**

```python
"""Init-repo agent: builds a knowledge base from an existing codebase."""
from __future__ import annotations
import json
import logging
from typing import Optional

from spec_agent.config import Config
from spec_agent.backends.factory import get_backend
from spec_agent.tools.fs_read import list_directory, read_source_file
from spec_agent.tools.wiki_read import read_wiki_file
from spec_agent.tools.wiki_write import write_wiki_file
from spec_agent.tools.wiki_search import search_wiki
from spec_agent.tools.wiki_index import update_index

logger = logging.getLogger(__name__)

_MAX_ITERATIONS = 30

INIT_TOOL_DEFINITIONS = [
    {
        "name": "list_directory",
        "description": (
            "List the directory tree of the repository. "
            "Skips .git, node_modules, __pycache__, build artifacts. "
            "Use this first to understand the repo structure."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "relative_path": {
                    "type": "string",
                    "description": "Path relative to repo root. Use '.' for root.",
                    "default": ".",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Max directory depth to traverse.",
                    "default": 3,
                },
            },
            "required": [],
        },
    },
    {
        "name": "read_source_file",
        "description": (
            "Read a source file from the repository. "
            "Content is capped at 8,000 characters. "
            "Do not read binary, lock, or generated files."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path relative to repo root, e.g. src/main/java/UserService.java",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_wiki",
        "description": "Search the Obsidian vault for existing pages before writing a new one.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms (3-5 keywords)"},
                "limit": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_wiki_file",
        "description": "Read an existing KB doc before updating it (only needed on --force re-run).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path relative to vault root, e.g. projects/my-service/overview.md",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_wiki_file",
        "description": (
            "Write a KB doc to the vault under projects/<service-name>/. "
            "Use mode='create' for new docs. "
            "Use mode='update' only if read_wiki_file confirmed the file exists."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path relative to vault root, e.g. projects/my-service/UserService.md",
                },
                "content": {"type": "string", "description": "Full markdown content"},
                "mode": {"type": "string", "enum": ["create", "update"], "default": "create"},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "update_index",
        "description": "Register the overview doc in index.md after all component docs are written. Call once per init run.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "ISO date, e.g. 2026-04-10"},
                "type": {
                    "type": "string",
                    "enum": ["feature", "bug", "refactor", "arch", "chore", "concept", "project"],
                },
                "title": {"type": "string"},
                "project": {"type": "string"},
                "path": {"type": "string", "description": "Vault path without .md"},
            },
            "required": ["date", "type", "title", "project", "path"],
        },
    },
]

_SHALLOW_SYSTEM_PROMPT = """\
You are an architecture-documentation agent. Your job is to build a knowledge base (KB) \
for an existing codebase in an Obsidian vault.

**Step 1 — Understand the repo (shallow scan):**
- Call list_directory with relative_path="." to see the top-level structure.
- Read these files first, in order of priority, if they exist:
  1. README.md, CLAUDE.md, .cursorrules, AGENTS.md
  2. Project config: pyproject.toml, pom.xml, package.json, build.gradle, go.mod
  3. Main entry point: main.py, app.py, Application.java, main.go, index.ts, server.py
- Based on what you have read, identify the 3-6 most architecturally significant components.

**Step 2 — Write the KB:**
- First write `projects/<service-name>/overview.md` — an anchor doc describing the service's purpose,
  tech stack, architecture, and linking to all components with [[wikilink]] syntax.
- Then write `projects/<service-name>/<ComponentName>.md` for each important component.
- Finally call update_index once for the overview doc (type: "project").

**Component doc template:**
```
---
type: kb-component
project: <service-name>
date: <today's date>
---
# <ComponentName>

## Purpose

## Key responsibilities

## Dependencies / interactions
<!-- [[wikilink]] to related components -->

## Important methods / endpoints

## Keywords
<!-- ALL relevant class names, method names, function names, synonyms — one per line.
     This section is critical: the search tool is a keyword grep, so include every
     identifier and synonym that could appear in a future diff related to this component. -->

## Related
```

**Rules:**
- Stay grounded in what you actually read — do not invent features.
- The Keywords section MUST include every class name, method name, package name, and synonym.
- Use [[wikilink]] syntax when referencing other KB docs.
- Call search_wiki before writing any doc to check if it already exists.
"""

_DEEP_SYSTEM_PROMPT = """\
You are an architecture-documentation agent. Your job is to build a knowledge base (KB) \
for an existing codebase in an Obsidian vault.

**Step 1 — Deep-dive the repo (--deep mode):**
- Call list_directory with relative_path="." to see the top-level structure.
- Call list_directory on subdirectories that look important.
- Read these files first, in order of priority:
  1. README.md, CLAUDE.md, .cursorrules, AGENTS.md
  2. Project config: pyproject.toml, pom.xml, package.json, build.gradle, go.mod
  3. Main entry point: main.py, app.py, Application.java, main.go, index.ts, server.py
- Then read source files for all significant components (up to 40 files total).
- Include test files to understand expected behaviour.
- Based on what you have read, identify ALL architecturally significant components.

**Step 2 — Write the KB:**
- First write `projects/<service-name>/overview.md` — an anchor doc describing the service's purpose,
  tech stack, architecture, and linking to all components with [[wikilink]] syntax.
- Then write `projects/<service-name>/<ComponentName>.md` for each component.
- Finally call update_index once for the overview doc (type: "project").

**Component doc template:**
```
---
type: kb-component
project: <service-name>
date: <today's date>
---
# <ComponentName>

## Purpose

## Key responsibilities

## Dependencies / interactions
<!-- [[wikilink]] to related components -->

## Important methods / endpoints

## Keywords
<!-- ALL relevant class names, method names, function names, synonyms — one per line.
     This section is critical: the search tool is a keyword grep, so include every
     identifier and synonym that could appear in a future diff related to this component. -->

## Related
```

**Rules:**
- Stay grounded in what you actually read — do not invent features.
- The Keywords section MUST include every class name, method name, package name, and synonym.
- Use [[wikilink]] syntax when referencing other KB docs.
- Call search_wiki before writing any doc to check if it already exists.
"""


def _dispatch_tool(
    name: str, tool_input: dict, repo_path: str, vault_path: str
) -> str:
    if name == "list_directory":
        return json.dumps(list_directory(
            repo_path,
            tool_input.get("relative_path", "."),
            tool_input.get("max_depth", 3),
        ))
    elif name == "read_source_file":
        return json.dumps(read_source_file(repo_path, tool_input["path"]))
    elif name == "search_wiki":
        results = search_wiki(vault_path, tool_input["query"], tool_input.get("limit", 5))
        return json.dumps(results)
    elif name == "read_wiki_file":
        return json.dumps(read_wiki_file(vault_path, tool_input["path"]))
    elif name == "write_wiki_file":
        return json.dumps(write_wiki_file(
            vault_path, tool_input["path"], tool_input["content"],
            mode=tool_input.get("mode", "create"),
        ))
    elif name == "update_index":
        return json.dumps(update_index(vault_path, tool_input))
    else:
        return json.dumps({"error": f"Unknown tool: {name}"})


def run_init_agent(
    repo_path: str,
    repo_name: str,
    cfg: Config,
    deep: bool = False,
    changed_files: Optional[list[str]] = None,
) -> None:
    """Run the KB initialisation agent for a repository."""
    vault_path = str(cfg.vault_path)
    backend = get_backend(cfg)
    system_prompt = _DEEP_SYSTEM_PROMPT if deep else _SHALLOW_SYSTEM_PROMPT

    mode_note = "deep scan (--deep)" if deep else "shallow scan"
    changed_note = ""
    if changed_files:
        listed = "\n".join(f"- {f}" for f in changed_files[:20])
        suffix = f"\n... and {len(changed_files) - 20} more" if len(changed_files) > 20 else ""
        changed_note = f"\n\nFiles changed since last init:\n{listed}{suffix}"

    user_message = (
        f"Build a knowledge base for this repository.\n\n"
        f"Repository name: {repo_name}\n"
        f"Repo root: {repo_path}\n"
        f"Mode: {mode_note}\n"
        f"Vault KB path: projects/{repo_name}/\n"
        f"{changed_note}\n\n"
        f"Follow the steps in your instructions to explore the repo and write the KB docs."
    )

    messages = [backend.make_user_message(user_message)]
    iteration = 0

    while iteration < _MAX_ITERATIONS:
        iteration += 1
        response = backend.chat(
            system=system_prompt,
            messages=messages,
            tools=INIT_TOOL_DEFINITIONS,
            max_tokens=4096,
        )

        if response.stop_reason == "end_turn":
            break

        if response.stop_reason == "tool_use":
            results = [
                _dispatch_tool(tc.name, tc.arguments, repo_path, vault_path)
                for tc in response.tool_calls
            ]
            messages.append(response.raw_assistant_turn)
            messages.extend(backend.make_tool_results_messages(response.tool_calls, results))
        else:
            logger.warning(
                "spec-agent init: unexpected stop_reason=%r at iteration %d, aborting",
                response.stop_reason, iteration,
            )
            break

    if iteration >= _MAX_ITERATIONS:
        logger.error(
            "spec-agent init: hit max iteration cap (%d) — possible runaway loop, aborting",
            _MAX_ITERATIONS,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_init_agent.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add spec_agent/init_agent.py tests/test_init_agent.py
git commit -m "feat: add init-repo agent with tool-use loop and KB system prompt"
```

---

## Task 4: CLI — `spec-agent init-repo`

**Files:**
- Modify: `spec_agent/cli.py`
- Modify: `tests/test_cli.py` (add `TestInitRepo` class)

- [ ] **Step 1: Write the failing tests**

Add this class to `tests/test_cli.py` (after the existing `TestHooks` class):

```python
# ---------------------------------------------------------------------------
# spec-agent init-repo
# ---------------------------------------------------------------------------

class TestInitRepo:
    def _setup(self, home: Path, vault_dir: Path) -> Path:
        """Write a minimal config pointing at vault_dir."""
        cfg_file = home / "config.yaml"
        cfg_file.write_text(f"vault_path: {vault_dir}\n")
        return cfg_file

    def test_errors_when_not_in_git_repo(
        self, runner: CliRunner, home: Path, vault_dir: Path
    ) -> None:
        cfg = self._setup(home, vault_dir)
        with patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "git")):
            result = runner.invoke(cli, ["init-repo", "--config", str(cfg)])
        assert result.exit_code != 0
        assert "Not a git repository" in result.output

    def test_warns_when_kb_exists_without_force(
        self, runner: CliRunner, home: Path, vault_dir: Path
    ) -> None:
        cfg = self._setup(home, vault_dir)
        # Pre-create the KB directory
        (vault_dir / "projects" / "my-service").mkdir(parents=True)

        with patch("subprocess.check_output", return_value=b"/code/my-service"):
            result = runner.invoke(cli, ["init-repo", "--config", str(cfg)])

        assert result.exit_code == 0
        assert "--force" in result.output

    def test_warns_when_vault_missing(
        self, runner: CliRunner, home: Path
    ) -> None:
        cfg = home / "config.yaml"
        cfg.write_text(f"vault_path: {home}/nonexistent-vault\n")

        with patch("subprocess.check_output", return_value=b"/code/my-service"):
            result = runner.invoke(cli, ["init-repo", "--config", str(cfg)])

        assert result.exit_code != 0
        assert "vault not found" in result.output

    def test_calls_run_init_agent(
        self, runner: CliRunner, home: Path, vault_dir: Path
    ) -> None:
        cfg = self._setup(home, vault_dir)

        with patch("subprocess.check_output", return_value=b"/code/my-service"), \
             patch("spec_agent.cli.run_init_agent") as mock_agent, \
             patch("spec_agent.cli.save_cache"):
            result = runner.invoke(cli, ["init-repo", "--config", str(cfg)])

        assert result.exit_code == 0, result.output
        mock_agent.assert_called_once()
        call_kwargs = mock_agent.call_args.kwargs
        assert call_kwargs["repo_name"] == "my-service"
        assert call_kwargs["deep"] is False

    def test_deep_flag_passed_to_agent(
        self, runner: CliRunner, home: Path, vault_dir: Path
    ) -> None:
        cfg = self._setup(home, vault_dir)

        with patch("subprocess.check_output", return_value=b"/code/my-service"), \
             patch("spec_agent.cli.run_init_agent") as mock_agent, \
             patch("spec_agent.cli.save_cache"):
            runner.invoke(cli, ["init-repo", "--deep", "--config", str(cfg)])

        call_kwargs = mock_agent.call_args.kwargs
        assert call_kwargs["deep"] is True

    def test_force_flag_checks_changed_files(
        self, runner: CliRunner, home: Path, vault_dir: Path
    ) -> None:
        cfg = self._setup(home, vault_dir)
        (vault_dir / "projects" / "my-service").mkdir(parents=True)

        with patch("subprocess.check_output", return_value=b"/code/my-service"), \
             patch("spec_agent.cli.run_init_agent") as mock_agent, \
             patch("spec_agent.cli.get_changed_files", return_value=["src/app.py"]) as mock_changed, \
             patch("spec_agent.cli.save_cache"):
            runner.invoke(cli, ["init-repo", "--force", "--config", str(cfg)])

        mock_changed.assert_called_once()
        call_kwargs = mock_agent.call_args.kwargs
        assert call_kwargs["changed_files"] == ["src/app.py"]
```

Also add `import subprocess` at the top of `tests/test_cli.py` if not already present.

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cli.py::TestInitRepo -v 2>&1 | head -20
```

Expected: errors about missing import or command not found.

- [ ] **Step 3: Add `init-repo` command to `spec_agent/cli.py`**

Add these imports at the top of `cli.py` (after existing imports):

```python
import subprocess
from spec_agent.init_agent import run_init_agent
from spec_agent.tools.init_cache import get_changed_files, save_cache
```

Add this command after the `configure` command:

```python
@cli.command("init-repo")
@click.option("--deep", is_flag=True, default=False, help="Full breadth-first scan (reads up to 40 files)")
@click.option("--force", is_flag=True, default=False, help="Update existing KB without prompting")
@click.option("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config.yaml")
def init_repo(deep: bool, force: bool, config: str) -> None:
    """Bootstrap a knowledge base for the current repo in the Obsidian vault."""
    # Detect repo root and name
    try:
        repo_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL
        ).decode().strip()
        repo_name = Path(repo_root).name
    except subprocess.CalledProcessError:
        console.print("[red]✗[/red] Not a git repository. Run this command from inside a repo.")
        raise SystemExit(1)

    cfg = load_config(Path(config))
    if not cfg.vault_path.exists():
        console.print(
            f"[yellow]spec-agent: vault not found at {cfg.vault_path}. Run: spec-agent init[/yellow]"
        )
        raise SystemExit(1)

    # Warn if KB already exists and --force not passed
    kb_path = cfg.vault_path / "projects" / repo_name
    if kb_path.exists() and not force:
        console.print(
            f"[yellow]⚠[/yellow]  KB already exists for [bold]{repo_name}[/bold]. "
            f"Run with [bold]--force[/bold] to update."
        )
        return

    # On --force re-run, surface changed files to the agent
    changed_files = get_changed_files(repo_root, repo_name) if force else None

    mode = "[deep]" if deep else "[shallow]"
    console.print(f"[cyan]spec-agent init-repo:[/cyan] scanning {repo_name} {mode}...")

    run_init_agent(
        repo_path=repo_root,
        repo_name=repo_name,
        cfg=cfg,
        deep=deep,
        changed_files=changed_files,
    )

    save_cache(repo_name, repo_root)
    console.print(f"[green]✓[/green] KB written to {kb_path}")
    console.print(
        f"[green]✓[/green] Cache saved — future [bold]--force[/bold] runs will focus on changed files"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_cli.py::TestInitRepo -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
pytest -v
```

Expected: all existing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add spec_agent/cli.py tests/test_cli.py
git commit -m "feat: add spec-agent init-repo command"
```

---

## Task 5: CLI — `spec-agent opt-out` / `spec-agent opt-in`

**Files:**
- Modify: `spec_agent/cli.py`
- Modify: `tests/test_cli.py` (add `TestOptOut` and `TestOptIn` classes)

- [ ] **Step 1: Write the failing tests**

Add these classes to `tests/test_cli.py` (after `TestInitRepo`):

```python
# ---------------------------------------------------------------------------
# spec-agent opt-out / opt-in
# ---------------------------------------------------------------------------

class TestOptOut:
    def _cfg_with_vault(self, home: Path) -> Path:
        cfg = home / "config.yaml"
        cfg.write_text(f"vault_path: {home}/vault\nignored_repos: []\n")
        return cfg

    def test_adds_repo_to_ignored_list(
        self, runner: CliRunner, home: Path
    ) -> None:
        cfg = self._cfg_with_vault(home)
        with patch("subprocess.check_output", return_value=b"/code/my-service"):
            result = runner.invoke(cli, ["opt-out", "--config", str(cfg)])
        assert result.exit_code == 0
        data = yaml.safe_load(cfg.read_text())
        assert "my-service" in data["ignored_repos"]

    def test_output_confirms_opt_out(
        self, runner: CliRunner, home: Path
    ) -> None:
        cfg = self._cfg_with_vault(home)
        with patch("subprocess.check_output", return_value=b"/code/my-service"):
            result = runner.invoke(cli, ["opt-out", "--config", str(cfg)])
        assert "my-service" in result.output
        assert "ignored" in result.output

    def test_no_op_when_already_ignored(
        self, runner: CliRunner, home: Path
    ) -> None:
        cfg = home / "config.yaml"
        cfg.write_text(f"vault_path: {home}/vault\nignored_repos:\n  - my-service\n")
        with patch("subprocess.check_output", return_value=b"/code/my-service"):
            result = runner.invoke(cli, ["opt-out", "--config", str(cfg)])
        assert result.exit_code == 0
        data = yaml.safe_load(cfg.read_text())
        assert data["ignored_repos"].count("my-service") == 1  # not duplicated

    def test_errors_when_not_in_git_repo(
        self, runner: CliRunner, home: Path
    ) -> None:
        cfg = self._cfg_with_vault(home)
        with patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "git")):
            result = runner.invoke(cli, ["opt-out", "--config", str(cfg)])
        assert result.exit_code != 0
        assert "Not a git repository" in result.output


class TestOptIn:
    def _cfg_with_ignored(self, home: Path) -> Path:
        cfg = home / "config.yaml"
        cfg.write_text(
            f"vault_path: {home}/vault\nignored_repos:\n  - my-service\n  - other-repo\n"
        )
        return cfg

    def test_removes_repo_from_ignored_list(
        self, runner: CliRunner, home: Path
    ) -> None:
        cfg = self._cfg_with_ignored(home)
        with patch("subprocess.check_output", return_value=b"/code/my-service"):
            result = runner.invoke(cli, ["opt-in", "--config", str(cfg)])
        assert result.exit_code == 0
        data = yaml.safe_load(cfg.read_text())
        assert "my-service" not in data["ignored_repos"]
        assert "other-repo" in data["ignored_repos"]  # other repo unaffected

    def test_output_confirms_opt_in(
        self, runner: CliRunner, home: Path
    ) -> None:
        cfg = self._cfg_with_ignored(home)
        with patch("subprocess.check_output", return_value=b"/code/my-service"):
            result = runner.invoke(cli, ["opt-in", "--config", str(cfg)])
        assert "my-service" in result.output

    def test_no_op_when_not_ignored(
        self, runner: CliRunner, home: Path
    ) -> None:
        cfg = home / "config.yaml"
        cfg.write_text(f"vault_path: {home}/vault\nignored_repos: []\n")
        with patch("subprocess.check_output", return_value=b"/code/my-service"):
            result = runner.invoke(cli, ["opt-in", "--config", str(cfg)])
        assert result.exit_code == 0
        assert "not currently ignored" in result.output

    def test_errors_when_not_in_git_repo(
        self, runner: CliRunner, home: Path
    ) -> None:
        cfg = home / "config.yaml"
        cfg.write_text(f"vault_path: {home}/vault\nignored_repos: []\n")
        with patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "git")):
            result = runner.invoke(cli, ["opt-in", "--config", str(cfg)])
        assert result.exit_code != 0
        assert "Not a git repository" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_cli.py::TestOptOut tests/test_cli.py::TestOptIn -v 2>&1 | head -20
```

Expected: errors about unknown commands `opt-out` and `opt-in`.

- [ ] **Step 3: Add `opt-out` and `opt-in` commands to `spec_agent/cli.py`**

Add this helper function before the `init_repo` command (or at the top of the command section):

```python
def _detect_repo_name() -> str:
    """Auto-detect repo name from the current directory via git."""
    try:
        repo_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL
        ).decode().strip()
        return Path(repo_root).name
    except subprocess.CalledProcessError:
        return ""
```

Add these commands after `init_repo`:

```python
@cli.command("opt-out")
@click.option("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config.yaml")
def opt_out(config: str) -> None:
    """Exclude the current repo from spec-agent's global hook."""
    repo_name = _detect_repo_name()
    if not repo_name:
        console.print("[red]✗[/red] Not a git repository. Run this command from inside a repo.")
        raise SystemExit(1)

    config_path = Path(config)
    cfg = load_config(config_path)
    if repo_name in cfg.ignored_repos:
        console.print(f"[dim]{repo_name} is already ignored.[/dim]")
        return

    cfg.ignored_repos.append(repo_name)
    save_config(cfg, config_path)
    console.print(
        f"[green]✓[/green] [bold]{repo_name}[/bold] added to ignored repos — "
        f"spec-agent will skip future pushes"
    )


@cli.command("opt-in")
@click.option("--config", default=str(DEFAULT_CONFIG_PATH), help="Path to config.yaml")
def opt_in(config: str) -> None:
    """Re-include the current repo in spec-agent's global hook."""
    repo_name = _detect_repo_name()
    if not repo_name:
        console.print("[red]✗[/red] Not a git repository. Run this command from inside a repo.")
        raise SystemExit(1)

    config_path = Path(config)
    cfg = load_config(config_path)
    if repo_name not in cfg.ignored_repos:
        console.print(f"[dim]{repo_name} is not currently ignored.[/dim]")
        return

    cfg.ignored_repos = [r for r in cfg.ignored_repos if r != repo_name]
    save_config(cfg, config_path)
    console.print(
        f"[green]✓[/green] [bold]{repo_name}[/bold] removed from ignored repos — "
        f"spec-agent is now active"
    )
```

Note: the `subprocess` import was already added in Task 4. If implementing Task 5 independently, add `import subprocess` at the top of `cli.py`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_cli.py::TestOptOut tests/test_cli.py::TestOptIn -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
pytest -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add spec_agent/cli.py tests/test_cli.py
git commit -m "feat: add spec-agent opt-out and opt-in commands"
```

---

## Task 6: Create GitHub Issue for Chunked Phase 2

- [ ] **Step 1: Create the issue**

```bash
gh issue create \
  --title "perf: chunked Phase 2 for init-repo (one LLM call per component)" \
  --body "$(cat <<'EOF'
## Background

The current `init-repo` agent uses a single tool-use loop (Approach A). As the LLM reads more files, the context window grows across iterations — for large repos in `--deep` mode this can accumulate significant tokens.

## Proposed Optimization

Split the init flow into two phases:

**Phase 1:** Shallow context bundle (README, dir tree, entry points) → single LLM call → LLM writes overview doc AND returns a structured list of N component names + relevant files.

**Phase 2:** For each component: one focused LLM call with only that component's files → writes that one doc.

This caps per-call token cost regardless of repo size, makes `--deep` predictable (cost scales linearly with number of components), and enables parallelism in future.

## Trade-offs

- More total LLM calls (N+1 instead of 1), but each call is small and bounded
- Requires structured output from Phase 1 (component list with file paths)
- Phase 1 and Phase 2 prompts need different system prompts

## Implementation Notes

- Phase 1 response needs to return JSON: `{"components": [{"name": "UserService", "files": ["src/UserService.py"]}]}`
- Phase 2 receives: component name, file contents, existing overview doc path for [[wikilink]] context
- Python orchestrates the loop, not the LLM
EOF
)"
```

- [ ] **Step 2: Note the issue number**

Copy the issue URL from the output (e.g., `https://github.com/v1shesh/spec-agent/issues/N`) and add it as a comment in `spec_agent/init_agent.py` near the `_MAX_ITERATIONS` constant:

```python
_MAX_ITERATIONS = 30  # See GitHub issue #N for chunked Phase 2 optimization
```

- [ ] **Step 3: Commit the comment**

```bash
git add spec_agent/init_agent.py
git commit -m "chore: reference chunked Phase 2 issue in init_agent"
```

---

## Final Verification

- [ ] **Run the full test suite**

```bash
pytest -v --tb=short
```

Expected: all tests PASS, no regressions.

- [ ] **Smoke test the CLI help**

```bash
spec-agent --help
```

Expected output includes: `init-repo`, `opt-out`, `opt-in` alongside existing commands.

- [ ] **Verify coverage**

```bash
pytest --cov=spec_agent --cov-report=term-missing
```

Expected: coverage stays at or above previous baseline for new modules.
