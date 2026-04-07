import pytest
from unittest.mock import MagicMock, patch
from spec_agent.agent import run_agent
from spec_agent.config import Config


@pytest.fixture
def cfg(vault_dir):
    return Config(vault_path=vault_dir)


def _make_tool_use_block(tool_name, tool_input, tool_id="tu_001"):
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input
    block.id = tool_id
    return block


def _make_text_block(text="Done."):
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _make_response(content, stop_reason="end_turn"):
    resp = MagicMock()
    resp.content = content
    resp.stop_reason = stop_reason
    return resp


def test_agent_runs_to_completion(cfg, vault_dir):
    """Agent makes tool calls then exits when stop_reason is end_turn."""
    # Simulate: classify_commit → write_wiki_file → update_index → end_turn
    call_count = 0

    def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_response(
                [_make_tool_use_block("classify_commit", {
                    "diff": "diff content",
                    "messages": ["fix: auth bug"],
                    "repo": "my-app",
                })],
                stop_reason="tool_use"
            )
        elif call_count == 2:
            return _make_response(
                [_make_tool_use_block("write_wiki_file", {
                    "path": "bugs/fix-auth.md",
                    "content": "# Fix auth\n\n## Root cause\nToken expired.",
                    "mode": "create",
                }, tool_id="tu_002")],
                stop_reason="tool_use"
            )
        elif call_count == 3:
            return _make_response(
                [_make_tool_use_block("update_index", {
                    "date": "2026-04-07",
                    "type": "bug",
                    "title": "Fix auth",
                    "project": "my-app",
                    "path": "bugs/fix-auth",
                }, tool_id="tu_003")],
                stop_reason="tool_use"
            )
        else:
            return _make_response([_make_text_block("Done.")], stop_reason="end_turn")

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = fake_create

    with patch("spec_agent.agent.anthropic.Anthropic", return_value=mock_client):
        run_agent(
            diff="diff content",
            commit_messages=["fix: auth bug"],
            repo_name="my-app",
            branch="main",
            cfg=cfg,
        )

    assert call_count == 4
    assert (vault_dir / "bugs" / "fix-auth.md").exists()
    index = (vault_dir / "index.md").read_text()
    assert "Fix auth" in index


def test_agent_skips_chore_commits(cfg):
    """Agent returns early without API calls for chore-type commits."""
    with patch("spec_agent.agent.anthropic.Anthropic") as mock_anthropic:
        run_agent(
            diff="",
            commit_messages=["chore: bump version"],
            repo_name="my-app",
            branch="main",
            cfg=cfg,
            _force_type="chore",  # test hook to bypass API classification
        )
        mock_anthropic.return_value.messages.create.assert_not_called()
