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
