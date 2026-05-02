import pytest
from unittest.mock import MagicMock, patch
from spec_agent.agent import run_agent, _MAX_ITERATIONS
from spec_agent.config import Config
from spec_agent.backends.base import ChatResponse, ToolCall


@pytest.fixture
def cfg(vault_dir):
    return Config(vault_path=vault_dir)


def _make_end_turn_response(text: str = "Done.") -> ChatResponse:
    return ChatResponse(
        stop_reason="end_turn",
        text=text,
        tool_calls=[],
        raw_assistant_turn={"role": "assistant", "content": text},
    )


def _make_tool_use_response(name: str, arguments: dict, tool_id: str = "tc_001") -> ChatResponse:
    tc = ToolCall(id=tool_id, name=name, arguments=arguments)
    return ChatResponse(
        stop_reason="tool_use",
        text=None,
        tool_calls=[tc],
        raw_assistant_turn={"role": "assistant", "content": None, "tool_calls": [{"name": name}]},
    )


def _make_unknown_stop_response() -> ChatResponse:
    return ChatResponse(
        stop_reason="stop_sequence",
        text=None,
        tool_calls=[],
        raw_assistant_turn={"role": "assistant", "content": None},
    )


# ---------------------------------------------------------------------------
# Core agent loop
# ---------------------------------------------------------------------------

def test_agent_runs_to_completion(cfg, vault_dir):
    """Agent makes tool calls then exits when stop_reason is end_turn."""
    call_count = 0

    def fake_chat(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_tool_use_response("write_wiki_file", {
                "path": "bugs/fix-auth.md",
                "content": "# Fix auth\n\n## Root cause\nToken expired.",
                "mode": "create",
            }, tool_id="tc_001")
        elif call_count == 2:
            return _make_tool_use_response("update_index", {
                "date": "2026-04-07", "type": "bug", "title": "Fix auth",
                "project": "my-app", "path": "bugs/fix-auth",
            }, tool_id="tc_002")
        else:
            return _make_end_turn_response("Done.")

    mock_backend = MagicMock()
    mock_backend.max_diff_chars = 10_000
    mock_backend.chat.side_effect = fake_chat
    mock_backend.make_user_message.side_effect = lambda c: {"role": "user", "content": c}
    mock_backend.make_tool_results_messages.return_value = [{"role": "tool", "content": "ok"}]

    with patch("spec_agent.agent.get_backend", return_value=mock_backend):
        run_agent(
            diff="diff content",
            commit_messages=["fix: auth bug"],
            repo_name="my-app",
            branch="main",
            cfg=cfg,
        )

    assert call_count == 3
    assert (vault_dir / "bugs" / "fix-auth.md").exists()
    index = (vault_dir / "index.md").read_text()
    assert "Fix auth" in index


def test_agent_skips_chore_commits(cfg):
    """Agent returns early without API calls for chore-type commits."""
    with patch("spec_agent.agent.get_backend") as mock_get_backend:
        run_agent(
            diff="",
            commit_messages=["chore: bump version"],
            repo_name="my-app",
            branch="main",
            cfg=cfg,
            _force_type="chore",
        )
        mock_get_backend.assert_not_called()


def test_agent_exits_on_unexpected_stop_reason(cfg):
    """Agent breaks out of loop cleanly on unexpected stop_reason."""
    mock_backend = MagicMock()
    mock_backend.max_diff_chars = 10_000
    mock_backend.chat.return_value = _make_unknown_stop_response()
    mock_backend.make_user_message.side_effect = lambda c: {"role": "user", "content": c}

    with patch("spec_agent.agent.get_backend", return_value=mock_backend):
        run_agent(
            diff="diff",
            commit_messages=["feat: new thing"],
            repo_name="my-app",
            branch="main",
            cfg=cfg,
        )

    assert mock_backend.chat.call_count == 1


def test_agent_respects_max_iterations_cap(cfg):
    """Agent halts after _MAX_ITERATIONS even if always returning tool_use."""
    mock_backend = MagicMock()
    mock_backend.max_diff_chars = 10_000
    mock_backend.chat.return_value = _make_tool_use_response("search_wiki", {"query": "foo"})
    mock_backend.make_user_message.side_effect = lambda c: {"role": "user", "content": c}
    mock_backend.make_tool_results_messages.return_value = [{"role": "tool", "content": "[]"}]

    with patch("spec_agent.agent.get_backend", return_value=mock_backend):
        run_agent(
            diff="diff",
            commit_messages=["feat: thing"],
            repo_name="my-app",
            branch="main",
            cfg=cfg,
        )

    assert mock_backend.chat.call_count == _MAX_ITERATIONS


def test_agent_dispatches_unknown_tool_gracefully(cfg, vault_dir):
    """Unknown tool names return an error JSON without crashing the loop."""
    call_count = 0

    def fake_chat(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_tool_use_response("nonexistent_tool", {})
        return _make_end_turn_response()

    mock_backend = MagicMock()
    mock_backend.max_diff_chars = 10_000
    mock_backend.chat.side_effect = fake_chat
    mock_backend.make_user_message.side_effect = lambda c: {"role": "user", "content": c}
    mock_backend.make_tool_results_messages.return_value = [{"role": "tool", "content": '{"error": "Unknown tool: nonexistent_tool"}'}]

    with patch("spec_agent.agent.get_backend", return_value=mock_backend):
        run_agent(
            diff="diff",
            commit_messages=["feat: thing"],
            repo_name="my-app",
            branch="main",
            cfg=cfg,
        )

    assert call_count == 2


def test_run_agent_injects_changed_symbols(cfg, vault_dir, mocker):
    """Mock extract_diff_symbols; 'Changed symbols' appears in user message."""
    mocker.patch(
        "spec_agent.agent._extract_diff_symbols",
        return_value={"agent.py": {"modified_functions": ["run_agent"], "modified_classes": []}},
    )
    mocker.patch("spec_agent.agent._DIFF_AST_AVAILABLE", True)

    messages_seen = []

    def fake_make_user_message(content):
        messages_seen.append(content)
        return {"role": "user", "content": content}

    mock_backend = MagicMock()
    mock_backend.max_diff_chars = 10_000
    mock_backend.chat.return_value = _make_end_turn_response()
    mock_backend.make_user_message.side_effect = fake_make_user_message

    with patch("spec_agent.agent.get_backend", return_value=mock_backend):
        run_agent(diff="diff content", commit_messages=["feat: thing"], repo_name="my-app", branch="main", cfg=cfg)

    assert messages_seen
    assert "Changed symbols" in messages_seen[0]


def test_run_agent_symbols_extraction_failure_does_not_raise(cfg, vault_dir, mocker):
    """If extract_diff_symbols raises, run_agent still completes and diff appears."""
    mocker.patch(
        "spec_agent.agent._extract_diff_symbols",
        side_effect=RuntimeError("parse error"),
    )
    mocker.patch("spec_agent.agent._DIFF_AST_AVAILABLE", True)

    messages_seen = []

    def fake_make_user_message(content):
        messages_seen.append(content)
        return {"role": "user", "content": content}

    mock_backend = MagicMock()
    mock_backend.max_diff_chars = 10_000
    mock_backend.chat.return_value = _make_end_turn_response()
    mock_backend.make_user_message.side_effect = fake_make_user_message

    with patch("spec_agent.agent.get_backend", return_value=mock_backend):
        run_agent(diff="diff content", commit_messages=["feat: thing"], repo_name="my-app", branch="main", cfg=cfg)

    assert messages_seen
    assert "diff content" in messages_seen[0]
