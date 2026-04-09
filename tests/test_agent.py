import pytest
import anthropic
from unittest.mock import MagicMock, patch, call
from spec_agent.agent import run_agent, _call_api_with_retry, _MAX_RETRIES, _MAX_ITERATIONS
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


# ---------------------------------------------------------------------------
# Core agent loop
# ---------------------------------------------------------------------------

def test_agent_runs_to_completion(cfg, vault_dir):
    """Agent makes tool calls then exits when stop_reason is end_turn."""
    call_count = 0

    def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_response(
                [_make_tool_use_block("write_wiki_file", {
                    "path": "bugs/fix-auth.md",
                    "content": "# Fix auth\n\n## Root cause\nToken expired.",
                    "mode": "create",
                }, tool_id="tu_001")],
                stop_reason="tool_use"
            )
        elif call_count == 2:
            return _make_response(
                [_make_tool_use_block("update_index", {
                    "date": "2026-04-07",
                    "type": "bug",
                    "title": "Fix auth",
                    "project": "my-app",
                    "path": "bugs/fix-auth",
                }, tool_id="tu_002")],
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

    assert call_count == 3
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
            _force_type="chore",
        )
        mock_anthropic.return_value.messages.create.assert_not_called()


def test_agent_exits_on_unexpected_stop_reason(cfg):
    """Agent breaks out of loop cleanly on unexpected stop_reason."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_response(
        [_make_text_block()], stop_reason="stop_sequence"
    )

    with patch("spec_agent.agent.anthropic.Anthropic", return_value=mock_client):
        run_agent(
            diff="diff",
            commit_messages=["feat: new thing"],
            repo_name="my-app",
            branch="main",
            cfg=cfg,
        )

    assert mock_client.messages.create.call_count == 1


def test_agent_respects_max_iterations_cap(cfg):
    """Agent halts after _MAX_ITERATIONS even if always returning tool_use."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_response(
        [_make_tool_use_block("search_wiki", {"query": "foo"})],
        stop_reason="tool_use",
    )

    with patch("spec_agent.agent.anthropic.Anthropic", return_value=mock_client):
        run_agent(
            diff="diff",
            commit_messages=["feat: thing"],
            repo_name="my-app",
            branch="main",
            cfg=cfg,
        )

    assert mock_client.messages.create.call_count == _MAX_ITERATIONS


def test_agent_dispatches_unknown_tool_gracefully(cfg, vault_dir):
    """Unknown tool names return an error JSON without crashing the loop."""
    call_count = 0

    def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return _make_response(
                [_make_tool_use_block("nonexistent_tool", {})],
                stop_reason="tool_use",
            )
        return _make_response([_make_text_block()], stop_reason="end_turn")

    mock_client = MagicMock()
    mock_client.messages.create.side_effect = fake_create

    with patch("spec_agent.agent.anthropic.Anthropic", return_value=mock_client):
        run_agent(
            diff="diff",
            commit_messages=["feat: thing"],
            repo_name="my-app",
            branch="main",
            cfg=cfg,
        )

    assert call_count == 2


# ---------------------------------------------------------------------------
# _call_api_with_retry — retry logic
# ---------------------------------------------------------------------------

def _make_mock_client(side_effects):
    """Return a mock Anthropic client whose messages.create raises/returns in sequence."""
    client = MagicMock()
    client.messages.create.side_effect = side_effects
    return client


def test_retry_succeeds_after_rate_limit():
    """Retries once after RateLimitError, then succeeds."""
    success = _make_response([_make_text_block()], stop_reason="end_turn")
    client = _make_mock_client([
        anthropic.RateLimitError.__new__(anthropic.RateLimitError),
        success,
    ])

    with patch("spec_agent.agent.time.sleep") as mock_sleep:
        result = _call_api_with_retry(client, model="m", max_tokens=100, messages=[])

    assert result is success
    mock_sleep.assert_called_once_with(2.0)  # base delay * 2^0


def _make_api_status_error(status_code):
    """Create a real anthropic.APIStatusError instance via __new__ to bypass constructor."""
    err = anthropic.APIStatusError.__new__(anthropic.APIStatusError)
    err.status_code = status_code
    err.message = f"HTTP {status_code}"
    return err


def test_retry_succeeds_after_server_error():
    """Retries on a retryable APIStatusError (503), then succeeds."""
    success = _make_response([_make_text_block()], stop_reason="end_turn")
    err = _make_api_status_error(503)
    client = _make_mock_client([err, success])

    with patch("spec_agent.agent.time.sleep"):
        result = _call_api_with_retry(client, model="m", max_tokens=100, messages=[])

    assert result is success


def test_retry_succeeds_after_connection_error():
    """Retries on APIConnectionError, then succeeds."""
    success = _make_response([_make_text_block()], stop_reason="end_turn")
    err = anthropic.APIConnectionError.__new__(anthropic.APIConnectionError)
    client = _make_mock_client([err, success])

    with patch("spec_agent.agent.time.sleep"):
        result = _call_api_with_retry(client, model="m", max_tokens=100, messages=[])

    assert result is success


def test_non_retryable_error_raises_immediately():
    """Non-retryable APIStatusError (e.g. 400) is re-raised without retry."""
    err = _make_api_status_error(400)
    client = _make_mock_client([err])

    with pytest.raises(anthropic.APIStatusError):
        _call_api_with_retry(client, model="m", max_tokens=100, messages=[])

    # Only called once — no retries
    assert client.messages.create.call_count == 1


def test_exhausted_retries_raise_runtime_error():
    """After _MAX_RETRIES failed attempts, RuntimeError is raised."""
    err = anthropic.RateLimitError.__new__(anthropic.RateLimitError)
    client = _make_mock_client([err] * (_MAX_RETRIES + 1))

    with patch("spec_agent.agent.time.sleep"):
        with pytest.raises(RuntimeError, match="failed after"):
            _call_api_with_retry(client, model="m", max_tokens=100, messages=[])

    assert client.messages.create.call_count == _MAX_RETRIES


def test_run_agent_exits_cleanly_after_exhausted_retries(cfg):
    """run_agent catches RuntimeError from exhausted retries and returns cleanly."""
    err = anthropic.RateLimitError.__new__(anthropic.RateLimitError)
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [err] * (_MAX_RETRIES + 1)

    with patch("spec_agent.agent.anthropic.Anthropic", return_value=mock_client):
        with patch("spec_agent.agent.time.sleep"):
            # Must not raise — agent swallows the error and returns
            run_agent(
                diff="diff",
                commit_messages=["feat: thing"],
                repo_name="my-app",
                branch="main",
                cfg=cfg,
            )


def test_run_agent_exits_cleanly_on_non_retryable_error(cfg):
    """run_agent catches non-retryable APIError and returns cleanly."""
    err = _make_api_status_error(400)
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = [err]

    with patch("spec_agent.agent.anthropic.Anthropic", return_value=mock_client):
        run_agent(
            diff="diff",
            commit_messages=["feat: thing"],
            repo_name="my-app",
            branch="main",
            cfg=cfg,
        )
