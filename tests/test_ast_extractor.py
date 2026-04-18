"""Tests for spec_agent/ast_extractor.py"""
from __future__ import annotations
import json
from pathlib import Path
import pytest

# Guard: skip all tree-sitter dependent tests if not installed
tree_sitter = pytest.importorskip("tree_sitter", reason="tree-sitter not installed")


class TestExtractPython:
    def test_extract_python_classes_and_functions(self, tmp_path: Path) -> None:
        """Parse a Python snippet; assert class/method/function names extracted."""
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
        """extract_repo_structure on .rb file returns files=[] and skipped has the path."""
        from spec_agent.ast_extractor import extract_repo_structure
        rb = tmp_path / "script.rb"
        rb.write_text("puts 'hello'")
        result = extract_repo_structure(str(tmp_path))
        assert result["files"] == []
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
