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
