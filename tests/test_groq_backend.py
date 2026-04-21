"""Tests for GroqBackend (Groq Cloud / OpenAI-compatible API)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from spec_agent.backends.base import ToolCall
from spec_agent.backends.groq_backend import GroqBackend, _parse_llama_xml_tool_call

# ---------------------------------------------------------------------------
# Helpers & fixtures
# ---------------------------------------------------------------------------

SAMPLE_TOOLS = [
    {
        "name": "search_wiki",
        "description": "Search the vault",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    }
]


def _mock_resp(
    content=None,
    tool_calls=None,
    finish_reason="stop",
    status_code=200,
) -> MagicMock:
    """Build a mock requests.Response."""
    mock = MagicMock()
    mock.status_code = status_code
    mock.text = "error body"
    mock.json.return_value = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls or [],
                },
                "finish_reason": finish_reason,
            }
        ]
    }
    return mock


@pytest.fixture(autouse=True)
def groq_api_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test-key")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGroqBackend:

    # 1. Text response (finish_reason="stop")
    def test_text_response(self):
        backend = GroqBackend()
        mock_resp = _mock_resp(content="hello", finish_reason="stop")

        with patch("requests.post", return_value=mock_resp):
            result = backend.chat("sys", [], [])

        assert result.stop_reason == "end_turn"
        assert result.text == "hello"
        assert result.tool_calls == []

    # 2. Tool call response
    def test_tool_call_response(self):
        backend = GroqBackend()
        raw_tool_calls = [
            {
                "id": "call_abc",
                "type": "function",
                "function": {
                    "name": "search_wiki",
                    "arguments": json.dumps({"query": "auth"}),
                },
            }
        ]
        mock_resp = _mock_resp(finish_reason="tool_calls", tool_calls=raw_tool_calls)

        with patch("requests.post", return_value=mock_resp):
            result = backend.chat("sys", [], SAMPLE_TOOLS)

        assert result.stop_reason == "tool_use"
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.id == "call_abc"
        assert tc.name == "search_wiki"
        assert tc.arguments == {"query": "auth"}
        assert isinstance(tc.arguments, dict)

    # 3. Missing GROQ_API_KEY raises RuntimeError without calling requests.post
    def test_missing_token_raises(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        backend = GroqBackend()

        with patch("requests.post") as mock_post:
            with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
                backend.chat("sys", [], [])

        mock_post.assert_not_called()

    # 4. Non-200 status raises RuntimeError with status code in message
    def test_non_200_raises(self):
        backend = GroqBackend()
        mock_resp = _mock_resp(status_code=500)

        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="500"):
                backend.chat("sys", [], [])

    # 5. 429 raises RuntimeError with "rate limit" in message (case-insensitive)
    def test_429_raises_rate_limit_message(self):
        backend = GroqBackend()
        mock_resp = _mock_resp(status_code=429)

        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="(?i)rate limit"):
                backend.chat("sys", [], [])

    # 6. make_user_message returns correct dict
    def test_make_user_message(self):
        backend = GroqBackend()
        result = backend.make_user_message("hi")
        assert result == {"role": "user", "content": "hi"}

    # 7. make_tool_results_messages uses tool_call_id key
    def test_make_tool_results_messages_uses_tool_call_id(self):
        backend = GroqBackend()
        tc1 = ToolCall(id="id1", name="search_wiki", arguments={})
        tc2 = ToolCall(id="id2", name="read_wiki_file", arguments={})
        msgs = backend.make_tool_results_messages([tc1, tc2], ["result1", "result2"])

        assert len(msgs) == 2
        assert msgs[0]["tool_call_id"] == "id1"
        assert msgs[0]["content"] == "result1"
        assert "name" not in msgs[0]
        assert msgs[1]["tool_call_id"] == "id2"
        assert msgs[1]["content"] == "result2"

    # 8. convert_tools wraps in "type": "function"
    def test_convert_tools(self):
        backend = GroqBackend()
        converted = backend.convert_tools(SAMPLE_TOOLS)
        assert len(converted) == 1
        assert converted[0]["type"] == "function"
        fn = converted[0]["function"]
        assert fn["name"] == "search_wiki"
        assert fn["description"] == "Search the vault"
        assert fn["parameters"] == SAMPLE_TOOLS[0]["input_schema"]

    # 9. raw_assistant_turn has "role" and "content" keys with correct values
    def test_raw_assistant_turn_has_role_content_keys(self):
        backend = GroqBackend()
        mock_resp = _mock_resp(content="hello")

        with patch("requests.post", return_value=mock_resp):
            result = backend.chat("sys", [], [])

        assert result.raw_assistant_turn["role"] == "assistant"
        assert result.raw_assistant_turn["content"] == "hello"

    # 10. raw_assistant_turn does NOT have "tool_calls" key when no tools called
    def test_raw_assistant_turn_no_tool_calls_key_on_text_response(self):
        backend = GroqBackend()
        mock_resp = _mock_resp(content="hello", finish_reason="stop")

        with patch("requests.post", return_value=mock_resp):
            result = backend.chat("sys", [], [])

        assert "tool_calls" not in result.raw_assistant_turn

    # 11. raw_assistant_turn tool_calls arguments is a JSON string (not dict)
    def test_raw_assistant_turn_tool_calls_arguments_is_string(self):
        backend = GroqBackend()
        raw_tool_calls = [
            {
                "id": "call_xyz",
                "type": "function",
                "function": {
                    "name": "search_wiki",
                    "arguments": json.dumps({"query": "test"}),
                },
            }
        ]
        mock_resp = _mock_resp(finish_reason="tool_calls", tool_calls=raw_tool_calls)

        with patch("requests.post", return_value=mock_resp):
            result = backend.chat("sys", [], SAMPLE_TOOLS)

        args = result.raw_assistant_turn["tool_calls"][0]["function"]["arguments"]
        assert isinstance(args, str)

    # 12. ToolCall.arguments is parsed to dict
    def test_arguments_parsed_to_dict(self):
        backend = GroqBackend()
        raw_tool_calls = [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "search_wiki",
                    "arguments": json.dumps({"query": "dict test"}),
                },
            }
        ]
        mock_resp = _mock_resp(finish_reason="tool_calls", tool_calls=raw_tool_calls)

        with patch("requests.post", return_value=mock_resp):
            result = backend.chat("sys", [], SAMPLE_TOOLS)

        assert isinstance(result.tool_calls[0].arguments, dict)
        assert result.tool_calls[0].arguments == {"query": "dict test"}

    # 13. Invalid JSON arguments raises RuntimeError
    def test_invalid_json_arguments_raises(self):
        backend = GroqBackend()
        raw_tool_calls = [
            {
                "id": "call_bad",
                "type": "function",
                "function": {
                    "name": "search_wiki",
                    "arguments": "not valid json",
                },
            }
        ]
        mock_resp = _mock_resp(finish_reason="tool_calls", tool_calls=raw_tool_calls)

        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(RuntimeError):
                backend.chat("sys", [], SAMPLE_TOOLS)

    # 14. Empty tools list omits "tools" key from payload
    def test_empty_tools_omits_key_from_payload(self):
        backend = GroqBackend()
        mock_resp = _mock_resp(content="ok")

        with patch("requests.post", return_value=mock_resp) as mock_post:
            backend.chat("sys", [], [])

        payload = mock_post.call_args[1]["json"]
        assert "tools" not in payload

    # 15. Non-empty tools includes "tools" key in payload
    def test_nonempty_tools_includes_key_in_payload(self):
        backend = GroqBackend()
        mock_resp = _mock_resp(content="ok")

        with patch("requests.post", return_value=mock_resp) as mock_post:
            backend.chat("sys", [], SAMPLE_TOOLS)

        payload = mock_post.call_args[1]["json"]
        assert "tools" in payload

    # 16. System prompt is prepended as first message
    def test_system_prompt_prepended(self):
        backend = GroqBackend()
        mock_resp = _mock_resp(content="ok")

        with patch("requests.post", return_value=mock_resp) as mock_post:
            backend.chat("my system prompt", [{"role": "user", "content": "hi"}], [])

        payload = mock_post.call_args[1]["json"]
        assert payload["messages"][0] == {"role": "system", "content": "my system prompt"}

    # 17. Bearer token is sent in Authorization header
    def test_bearer_header_sent(self):
        backend = GroqBackend()
        mock_resp = _mock_resp(content="ok")

        with patch("requests.post", return_value=mock_resp) as mock_post:
            backend.chat("sys", [], [])

        headers = mock_post.call_args[1]["headers"]
        assert headers["Authorization"] == "Bearer gsk_test-key"

    # 18. finish_reason="length" maps to stop_reason="end_turn"
    def test_finish_reason_length_maps_to_end_turn(self):
        backend = GroqBackend()
        mock_resp = _mock_resp(content="truncated", finish_reason="length")

        with patch("requests.post", return_value=mock_resp):
            result = backend.chat("sys", [], [])

        assert result.stop_reason == "end_turn"

    # 19. Empty choices list raises RuntimeError
    def test_empty_choices_raises(self):
        backend = GroqBackend()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"choices": []}

        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(RuntimeError):
                backend.chat("sys", [], [])

    # 20. Multiple tool calls in response are all preserved
    def test_multiple_tool_calls(self):
        backend = GroqBackend()
        raw_tool_calls = [
            {
                "id": "call_first",
                "type": "function",
                "function": {
                    "name": "search_wiki",
                    "arguments": json.dumps({"query": "first"}),
                },
            },
            {
                "id": "call_second",
                "type": "function",
                "function": {
                    "name": "read_wiki_file",
                    "arguments": json.dumps({"path": "features/auth.md"}),
                },
            },
        ]
        mock_resp = _mock_resp(finish_reason="tool_calls", tool_calls=raw_tool_calls)

        with patch("requests.post", return_value=mock_resp):
            result = backend.chat("sys", [], SAMPLE_TOOLS)

        assert len(result.tool_calls) == 2
        assert result.tool_calls[0].id == "call_first"
        assert result.tool_calls[1].id == "call_second"

    # 21. ast_budget_chars returns None (no truncation needed — 128k context)
    def test_ast_budget_chars_is_none(self):
        backend = GroqBackend()
        assert not hasattr(backend, "ast_budget_chars") or backend.ast_budget_chars is None

    # 22. Default model is "llama-3.3-70b-versatile"
    def test_default_model(self):
        backend = GroqBackend()
        assert backend.model == "llama-3.3-70b-versatile"

    # 23. Custom model accepted in constructor
    def test_custom_model(self):
        backend = GroqBackend(model="llama-3.1-8b-instant")
        assert backend.model == "llama-3.1-8b-instant"

    # 24. Correct base URL used in POST
    def test_correct_base_url(self):
        backend = GroqBackend()
        mock_resp = _mock_resp(content="ok")

        with patch("requests.post", return_value=mock_resp) as mock_post:
            backend.chat("sys", [], [])

        call_url = mock_post.call_args[0][0]
        assert call_url == "https://api.groq.com/openai/v1/chat/completions"


class TestParseLlamaXmlToolCall:

    # 25. Parses object format with > separator: <function=name {"key": "val"}>
    def test_parses_object_format_with_gt(self):
        raw = '<function=search_wiki {"query": "auth"}></function>'
        tc = _parse_llama_xml_tool_call(raw)
        assert tc is not None
        assert tc.name == "search_wiki"
        assert tc.arguments == {"query": "auth"}
        assert tc.id.startswith("call_")

    # 26. Parses object format without space or >: <function=name{...}</function>
    def test_parses_object_format_no_space_no_gt(self):
        raw = '<function=update_index{"date": "2026-01-01", "type": "bug", "title": "Fix", "project": "myapp", "path": "bugs/fix"}</function>'
        tc = _parse_llama_xml_tool_call(raw)
        assert tc is not None
        assert tc.name == "update_index"
        assert tc.arguments["date"] == "2026-01-01"
        assert tc.arguments["type"] == "bug"

    # 27. Parses array format: <function=name [{"key": "val"}]>
    def test_parses_array_format(self):
        raw = '<function=search_wiki [{"limit": 5, "query": "feat"}]></function>'
        tc = _parse_llama_xml_tool_call(raw)
        assert tc is not None
        assert tc.name == "search_wiki"
        assert tc.arguments == {"limit": 5, "query": "feat"}

    # 27. Returns None when format is not recognized
    def test_returns_none_on_unrecognized_format(self):
        assert _parse_llama_xml_tool_call("some random error text") is None

    # 28. Returns None when JSON is malformed
    def test_returns_none_on_malformed_json(self):
        raw = "<function=search_wiki {bad json}>"
        assert _parse_llama_xml_tool_call(raw) is None

    # 29. Each call generates a unique id
    def test_unique_ids(self):
        raw = '<function=search_wiki {"query": "x"}></function>'
        ids = {_parse_llama_xml_tool_call(raw).id for _ in range(5)}
        assert len(ids) == 5


class TestGroqBackendXmlFallback:

    # 30. 400 tool_use_failed with parseable XML (with >) recovers
    def test_tool_use_failed_recovery(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test-key")
        backend = GroqBackend()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "tool_use_failed"
        mock_resp.json.return_value = {
            "error": {
                "code": "tool_use_failed",
                "failed_generation": '<function=search_wiki {"query": "auth"}></function>',
            }
        }

        with patch("requests.post", return_value=mock_resp):
            result = backend.chat("sys", [], SAMPLE_TOOLS)

        assert result.stop_reason == "tool_use"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "search_wiki"
        assert result.tool_calls[0].arguments == {"query": "auth"}
        assert result.raw_assistant_turn["role"] == "assistant"
        assert result.raw_assistant_turn["content"] is None

    # 30b. 400 tool_use_failed with no space and no >: <function=name{...}</function>
    def test_tool_use_failed_recovery_no_space_no_gt(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test-key")
        backend = GroqBackend()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "tool_use_failed"
        mock_resp.json.return_value = {
            "error": {
                "code": "tool_use_failed",
                "failed_generation": '<function=update_index{"date": "2026-01-01", "type": "feat", "title": "Test", "project": "myapp", "path": "features/test"}</function>',
            }
        }

        with patch("requests.post", return_value=mock_resp):
            result = backend.chat("sys", [], SAMPLE_TOOLS)

        assert result.stop_reason == "tool_use"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].name == "update_index"
        assert result.tool_calls[0].arguments["type"] == "feat"

    # 31. 400 tool_use_failed with unparseable XML still raises RuntimeError
    def test_tool_use_failed_unparseable_raises(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test-key")
        backend = GroqBackend()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "tool_use_failed"
        mock_resp.json.return_value = {
            "error": {
                "code": "tool_use_failed",
                "failed_generation": "garbled output no function tag",
            }
        }

        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="400"):
                backend.chat("sys", [], SAMPLE_TOOLS)

    # 32. 400 with non-tool_use_failed code raises RuntimeError
    def test_400_non_tool_use_failed_raises(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "gsk_test-key")
        backend = GroqBackend()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "bad request"
        mock_resp.json.return_value = {
            "error": {"code": "invalid_request_error", "message": "bad"}
        }

        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="400"):
                backend.chat("sys", [], [])
