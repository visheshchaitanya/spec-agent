"""Tests for spec_agent/ast_extractor.py"""
from __future__ import annotations
import json
from pathlib import Path
import pytest

# Note: only tests that actually call tree-sitter use importorskip per-test.
# Tests for pure-Python paths (extract_diff_symbols, graceful fallback) run always.


class TestExtractPython:
    def test_extract_python_classes_and_functions(self, tmp_path: Path) -> None:
        """Parse a Python snippet; assert class/method/function names extracted."""
        pytest.importorskip("tree_sitter", reason="tree-sitter not installed")
        pytest.importorskip("tree_sitter_python", reason="tree-sitter-python not installed")
        from spec_agent.ast_extractor import _extract_file
        f = tmp_path / "sample.py"
        f.write_text(
            "class MyClass:\n"
            "    def my_method(self): pass\n"
            "\n"
            "def top_level_func(): pass\n"
        )
        result = _extract_file(f, ".py", tmp_path)
        assert result["language"] == "python"
        class_names = [c["name"] for c in result["classes"]]
        assert "MyClass" in class_names
        method_names = result["classes"][0]["methods"]
        assert "my_method" in method_names
        func_names = [fn["name"] for fn in result["functions"]]
        assert "top_level_func" in func_names

    def test_extract_python_imports(self, tmp_path: Path) -> None:
        """Both import forms appear in imports list."""
        pytest.importorskip("tree_sitter", reason="tree-sitter not installed")
        pytest.importorskip("tree_sitter_python", reason="tree-sitter-python not installed")
        from spec_agent.ast_extractor import _extract_file
        f = tmp_path / "sample.py"
        f.write_text("import os\nfrom pathlib import Path\n")
        result = _extract_file(f, ".py", tmp_path)
        joined = " ".join(result["imports"])
        assert "os" in joined
        assert "pathlib" in joined


class TestExtractUnsupported:
    def test_extract_unsupported_extension(self, tmp_path: Path) -> None:
        """extract_repo_structure on .rb file returns files=[].
        When tree-sitter is installed, .rb appears in skipped.
        When tree-sitter is absent, result has 'error' key (early return)."""
        from spec_agent.ast_extractor import extract_repo_structure
        rb = tmp_path / "script.rb"
        rb.write_text("puts 'hello'")
        result = extract_repo_structure(str(tmp_path))
        assert result["files"] == []
        if "error" in result:
            # tree-sitter not installed — graceful fallback, no file walking
            assert "tree-sitter" in result["error"]
        else:
            skipped_str = " ".join(result.get("skipped", []))
            assert "script.rb" in skipped_str

    def test_extract_repo_structure_empty_dir(self, tmp_path: Path) -> None:
        """Empty directory returns files=[], skipped=[]."""
        from spec_agent.ast_extractor import extract_repo_structure
        result = extract_repo_structure(str(tmp_path))
        assert result["files"] == []
        assert result["skipped"] == []

    def test_extract_repo_structure_skips_git_dir(self, tmp_path: Path) -> None:
        """Files inside .git/ are not extracted."""
        pytest.importorskip("tree_sitter_python", reason="tree-sitter-python not installed")
        from spec_agent.ast_extractor import extract_repo_structure
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "hook.py").write_text("def hook(): pass")
        result = extract_repo_structure(str(tmp_path))
        paths = [f["path"] for f in result["files"]]
        assert not any(".git" in p for p in paths)

    def test_extract_repo_structure_bad_file_does_not_abort(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A file that raises during parsing is skipped; others still complete."""
        pytest.importorskip("tree_sitter_python", reason="tree-sitter-python not installed")
        from spec_agent import ast_extractor
        (tmp_path / "good.py").write_text("def foo(): pass")
        (tmp_path / "bad.py").write_text("def bar(): pass")

        original = ast_extractor._extract_file
        call_count = 0

        def patched(abs_path, ext, repo_root):
            nonlocal call_count
            call_count += 1
            if abs_path.name == "bad.py":
                raise RuntimeError("parse error")
            return original(abs_path, ext, repo_root)

        monkeypatch.setattr(ast_extractor, "_extract_file", patched)
        result = ast_extractor.extract_repo_structure(str(tmp_path))
        assert len(result["files"]) == 1  # good.py extracted
        assert any("bad.py" in s for s in result["skipped"])


class TestWalkRepo:
    def test_walk_repo_returns_files(self, tmp_path: Path) -> None:
        """_walk_repo returns files and skips hidden dirs and skip dirs."""
        from spec_agent.ast_extractor import _walk_repo
        (tmp_path / "main.py").write_text("x = 1")
        (tmp_path / ".hidden.py").write_text("x = 1")
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("data")
        results = _walk_repo(str(tmp_path))
        rel_results = [Path(r).name for r in results]
        assert "main.py" in rel_results
        assert ".hidden.py" not in rel_results
        assert "config" not in rel_results

    def test_walk_repo_skips_symlinks_outside_root(self, tmp_path: Path) -> None:
        """Symlinks pointing outside the repo root are skipped."""
        import os
        from spec_agent.ast_extractor import _walk_repo
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "secret.py").write_text("x = 1")
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "main.py").write_text("y = 2")
        # Create a symlink inside repo that points outside
        link = repo / "escape.py"
        link.symlink_to(outside / "secret.py")
        results = _walk_repo(str(repo))
        names = [Path(r).name for r in results]
        assert "main.py" in names
        assert "escape.py" not in names  # symlink escaping root rejected


class TestRepoStructureSecurityPaths:
    def test_extract_repo_structure_rejects_out_of_root_path(self, tmp_path: Path) -> None:
        """Caller-supplied files outside repo_root are rejected and go to skipped."""
        from spec_agent.ast_extractor import extract_repo_structure
        repo = tmp_path / "repo"
        repo.mkdir()
        outside = tmp_path / "outside.py"
        outside.write_text("x = 1")
        result = extract_repo_structure(
            str(repo),
            files=[str(outside)],
        )
        assert result["files"] == []
        # Either error (no tree-sitter) or the path lands in skipped
        if "error" not in result:
            assert any("outside" in s for s in result.get("skipped", []))


class TestExtractDiffSymbols:
    def test_extract_diff_symbols_basic(self) -> None:
        """A minimal diff touching a Python class method returns correct symbols."""
        from spec_agent.ast_extractor import extract_diff_symbols
        diff = (
            "--- a/agent.py\n"
            "+++ b/agent.py\n"
            "@@ -10,6 +10,8 @@ def run_agent():\n"
            "+    new_line = True\n"
            "-    old_line = False\n"
        )
        result = extract_diff_symbols(diff)
        assert "agent.py" in result
        assert "run_agent" in result["agent.py"]["modified_functions"]

    def test_extract_diff_symbols_empty_diff(self) -> None:
        """Empty string returns empty dict."""
        from spec_agent.ast_extractor import extract_diff_symbols
        assert extract_diff_symbols("") == {}

    def test_extract_diff_symbols_unknown_extension(self) -> None:
        """Diff for a .rb file returns empty dict (extension not in LANG_MAP)."""
        from spec_agent.ast_extractor import extract_diff_symbols
        diff = (
            "--- a/script.rb\n"
            "+++ b/script.rb\n"
            "@@ -1,2 +1,3 @@ def hello\n"
            "+  puts 'world'\n"
        )
        result = extract_diff_symbols(diff)
        assert result == {}

    def test_extract_diff_symbols_with_class_keyword(self) -> None:
        """Diff with 'class' keyword in hunk header populates modified_classes."""
        from spec_agent.ast_extractor import extract_diff_symbols
        diff = (
            "--- a/models.py\n"
            "+++ b/models.py\n"
            "@@ -5,3 +5,5 @@ class UserModel:\n"
            "+    new_field = True\n"
        )
        result = extract_diff_symbols(diff)
        assert "models.py" in result
        assert "UserModel" in result["models.py"]["modified_classes"]

    def test_extract_diff_symbols_multi_file(self) -> None:
        """Diff with two files produces entries for both."""
        from spec_agent.ast_extractor import extract_diff_symbols
        diff = (
            "--- a/agent.py\n"
            "+++ b/agent.py\n"
            "@@ -1,2 +1,3 @@ def run_agent():\n"
            "+    x = 1\n"
            "--- a/config.py\n"
            "+++ b/config.py\n"
            "@@ -10,2 +10,3 @@ def load_config():\n"
            "+    y = 2\n"
        )
        result = extract_diff_symbols(diff)
        assert "agent.py" in result
        assert "config.py" in result
        assert "run_agent" in result["agent.py"]["modified_functions"]
        assert "load_config" in result["config.py"]["modified_functions"]
