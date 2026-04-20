"""Tests for the init-repo agent loop."""
from __future__ import annotations
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from spec_agent.init_agent import run_init_agent, _MAX_ITERATIONS, _MAX_ITERATIONS_AST, _MAX_ITERATIONS_FALLBACK
from spec_agent.config import Config
from spec_agent.backends.base import ChatResponse, ToolCall
import json


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
        call_count = 0
        results_seen = []

        def fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _tool_use("list_directory", {"relative_path": "."})
            return _end_turn()

        def capture(tool_calls, results):
            results_seen.extend(results)
            return [{"role": "tool", "content": r} for r in results]

        mock_backend = MagicMock()
        mock_backend.chat.side_effect = fake_chat
        mock_backend.make_user_message.side_effect = lambda c: {"role": "user", "content": c}
        mock_backend.make_tool_results_messages.side_effect = capture

        with patch("spec_agent.init_agent.get_backend", return_value=mock_backend):
            run_init_agent(repo_path=str(repo), repo_name="my-service", cfg=cfg)

        import json
        tree_data = json.loads(results_seen[0])
        assert "README.md" in tree_data.get("tree", "")

    def test_dispatches_read_source_file(self, cfg: Config, repo: Path) -> None:
        """read_source_file tool call returns file content."""
        call_count = 0
        results_seen = []

        def fake_chat(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _tool_use("read_source_file", {"path": "README.md"})
            return _end_turn()

        def capture(tool_calls, results):
            results_seen.extend(results)
            return [{"role": "tool", "content": r} for r in results]

        mock_backend = MagicMock()
        mock_backend.chat.side_effect = fake_chat
        mock_backend.make_user_message.side_effect = lambda c: {"role": "user", "content": c}
        mock_backend.make_tool_results_messages.side_effect = capture

        with patch("spec_agent.init_agent.get_backend", return_value=mock_backend):
            run_init_agent(repo_path=str(repo), repo_name="my-service", cfg=cfg)

        import json
        result = json.loads(results_seen[0])
        assert "My Service" in result.get("content", "")

    def test_respects_max_iterations_fallback(self, cfg: Config, repo: Path) -> None:
        """Agent halts after _MAX_ITERATIONS_FALLBACK when AST extraction yields no files."""
        mock_backend = MagicMock()
        mock_backend.chat.return_value = _tool_use("list_directory", {})
        mock_backend.make_user_message.side_effect = lambda c: {"role": "user", "content": c}
        mock_backend.make_tool_results_messages.return_value = [{"role": "tool", "content": '{"tree": ""}'}]

        empty_ast = {"files": [], "skipped": []}
        with patch("spec_agent.init_agent.get_backend", return_value=mock_backend), \
             patch("spec_agent.init_agent._extract_repo_structure", return_value=empty_ast):
            run_init_agent(repo_path=str(repo), repo_name="my-service", cfg=cfg)

        assert mock_backend.chat.call_count == _MAX_ITERATIONS_FALLBACK

    def test_respects_max_iterations_ast(self, cfg: Config, repo: Path) -> None:
        """Agent halts after _MAX_ITERATIONS_AST when AST extraction yields files."""
        mock_backend = MagicMock()
        mock_backend.chat.return_value = _tool_use("list_directory", {})
        mock_backend.make_user_message.side_effect = lambda c: {"role": "user", "content": c}
        mock_backend.make_tool_results_messages.return_value = [{"role": "tool", "content": '{"tree": ""}'}]

        ast_result = {"files": [{"path": "main.py", "language": "python", "classes": [], "functions": [], "imports": []}], "skipped": []}
        with patch("spec_agent.init_agent.get_backend", return_value=mock_backend), \
             patch("spec_agent.init_agent._extract_repo_structure", return_value=ast_result):
            run_init_agent(repo_path=str(repo), repo_name="my-service", cfg=cfg)

        assert mock_backend.chat.call_count == _MAX_ITERATIONS_AST

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

    def test_run_init_agent_injects_ast_block(
        self, cfg: Config, repo: Path, mocker
    ) -> None:
        """When AST extraction returns data, <repo-structure> appears in user message."""
        mock_ast = mocker.patch(
            "spec_agent.init_agent._extract_repo_structure",
            return_value={
                "files": [
                    {"path": "src/main.py", "language": "python", "classes": [], "functions": [{"name": "main", "line": 1}], "imports": []}
                ],
                "skipped": [],
            },
        )
        mocker.patch("spec_agent.init_agent._AST_AVAILABLE", True)

        messages_seen = []

        def fake_make_user_message(content):
            messages_seen.append(content)
            return {"role": "user", "content": content}

        mock_backend = MagicMock()
        mock_backend.chat.return_value = _end_turn()
        mock_backend.make_user_message.side_effect = fake_make_user_message
        mock_backend.ast_budget_chars = None  # unlimited — don't truncate AST

        with patch("spec_agent.init_agent.get_backend", return_value=mock_backend):
            run_init_agent(repo_path=str(repo), repo_name="my-service", cfg=cfg)

        assert messages_seen
        assert "<repo-structure>" in messages_seen[0]
        assert "main.py" in messages_seen[0]

    def test_run_init_agent_fallback_when_ast_empty(
        self, cfg: Config, repo: Path, mocker
    ) -> None:
        """When AST returns no files, <repo-structure> does NOT appear in user message."""
        mocker.patch(
            "spec_agent.init_agent._extract_repo_structure",
            return_value={"files": [], "skipped": ["foo.rb"]},
        )
        mocker.patch("spec_agent.init_agent._AST_AVAILABLE", True)

        messages_seen = []

        def fake_make_user_message(content):
            messages_seen.append(content)
            return {"role": "user", "content": content}

        mock_backend = MagicMock()
        mock_backend.chat.return_value = _end_turn()
        mock_backend.make_user_message.side_effect = fake_make_user_message

        with patch("spec_agent.init_agent.get_backend", return_value=mock_backend):
            run_init_agent(repo_path=str(repo), repo_name="my-service", cfg=cfg)

        assert messages_seen
        assert "<repo-structure>" not in messages_seen[0]

    def test_run_init_agent_uses_ast_system_prompt(
        self, cfg: Config, repo: Path, mocker
    ) -> None:
        """When AST data is available, system prompt contains 'pre-extracted'."""
        mocker.patch(
            "spec_agent.init_agent._extract_repo_structure",
            return_value={
                "files": [{"path": "main.py", "language": "python", "classes": [], "functions": [], "imports": []}],
                "skipped": [],
            },
        )
        mocker.patch("spec_agent.init_agent._AST_AVAILABLE", True)

        prompts_seen = []

        def fake_chat(**kwargs):
            prompts_seen.append(kwargs.get("system", ""))
            return _end_turn()

        mock_backend = MagicMock()
        mock_backend.chat.side_effect = fake_chat
        mock_backend.make_user_message.side_effect = lambda c: {"role": "user", "content": c}

        with patch("spec_agent.init_agent.get_backend", return_value=mock_backend):
            run_init_agent(repo_path=str(repo), repo_name="my-service", cfg=cfg)

        assert prompts_seen
        assert "pre-extracted" in prompts_seen[0]

    def test_run_init_agent_uses_fallback_system_prompt(
        self, cfg: Config, repo: Path, mocker
    ) -> None:
        """When AST data is empty, system prompt still contains 'list_directory'."""
        mocker.patch(
            "spec_agent.init_agent._extract_repo_structure",
            return_value={"files": [], "skipped": []},
        )
        mocker.patch("spec_agent.init_agent._AST_AVAILABLE", True)

        prompts_seen = []

        def fake_chat(**kwargs):
            prompts_seen.append(kwargs.get("system", ""))
            return _end_turn()

        mock_backend = MagicMock()
        mock_backend.chat.side_effect = fake_chat
        mock_backend.make_user_message.side_effect = lambda c: {"role": "user", "content": c}

        with patch("spec_agent.init_agent.get_backend", return_value=mock_backend):
            run_init_agent(repo_path=str(repo), repo_name="my-service", cfg=cfg)

        assert prompts_seen
        assert "list_directory" in prompts_seen[0]
