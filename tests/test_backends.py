"""Tests for LLM backend implementations."""
from __future__ import annotations
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from spec_agent.backends.base import ChatResponse, LLMBackend, ToolCall, anthropic_to_openai_tools
from spec_agent.backends.anthropic_backend import AnthropicBackend
from spec_agent.backends.ollama_backend import OllamaBackend
from spec_agent.backends.factory import get_backend
from spec_agent.config import Config


# ---------------------------------------------------------------------------
# Shared fixtures
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


@pytest.fixture
def base_cfg(tmp_path: Path) -> Config:
    return Config(vault_path=tmp_path)


# ---------------------------------------------------------------------------
# base.py helpers
# ---------------------------------------------------------------------------

class TestAnthropicToOpenAITools:
    def test_converts_input_schema_to_parameters(self) -> None:
        converted = anthropic_to_openai_tools(SAMPLE_TOOLS)
        assert len(converted) == 1
        fn = converted[0]
        assert fn["type"] == "function"
        assert fn["function"]["name"] == "search_wiki"
        assert fn["function"]["description"] == "Search the vault"
        assert "query" in fn["function"]["parameters"]["properties"]

    def test_missing_description_defaults_to_empty(self) -> None:
        tools = [{"name": "foo", "input_schema": {"type": "object", "properties": {}}}]
        converted = anthropic_to_openai_tools(tools)
        assert converted[0]["function"]["description"] == ""


# ---------------------------------------------------------------------------
# AnthropicBackend
# ---------------------------------------------------------------------------

class TestAnthropicBackend:
    def _make_mock_response(self, stop_reason: str, blocks: list) -> MagicMock:
        resp = MagicMock()
        resp.stop_reason = stop_reason
        resp.content = blocks
        return resp

    def _text_block(self, text: str) -> MagicMock:
        b = MagicMock()
        b.type = "text"
        b.text = text
        return b

    def _tool_block(self, tool_id: str, name: str, inputs: dict) -> MagicMock:
        b = MagicMock()
        b.type = "tool_use"
        b.id = tool_id
        b.name = name
        b.input = inputs
        return b

    def test_end_turn_response(self) -> None:
        backend = AnthropicBackend(api_key="test-key")
        mock_resp = self._make_mock_response("end_turn", [self._text_block("hello")])

        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_resp
            result = backend.chat("sys", [{"role": "user", "content": "hi"}], SAMPLE_TOOLS)

        assert result.stop_reason == "end_turn"
        assert result.text == "hello"
        assert result.tool_calls == []

    def test_tool_use_response(self) -> None:
        backend = AnthropicBackend(api_key="test-key")
        tool_block = self._tool_block("abc123", "search_wiki", {"query": "auth"})
        mock_resp = self._make_mock_response("tool_use", [tool_block])

        with patch("anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.create.return_value = mock_resp
            result = backend.chat("sys", [], SAMPLE_TOOLS)

        assert result.stop_reason == "tool_use"
        assert len(result.tool_calls) == 1
        assert result.tool_calls[0].id == "abc123"
        assert result.tool_calls[0].name == "search_wiki"
        assert result.tool_calls[0].arguments == {"query": "auth"}

    def test_make_user_message(self) -> None:
        backend = AnthropicBackend(api_key="test-key")
        msg = backend.make_user_message("hello")
        assert msg == {"role": "user", "content": "hello"}

    def test_make_tool_results_messages_packs_into_one(self) -> None:
        backend = AnthropicBackend(api_key="test-key")
        tc1 = ToolCall(id="id1", name="search_wiki", arguments={})
        tc2 = ToolCall(id="id2", name="read_wiki_file", arguments={})
        msgs = backend.make_tool_results_messages([tc1, tc2], ["result1", "result2"])

        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"
        assert len(msgs[0]["content"]) == 2
        assert msgs[0]["content"][0]["tool_use_id"] == "id1"
        assert msgs[0]["content"][1]["tool_use_id"] == "id2"

    def test_convert_tools_unchanged(self) -> None:
        backend = AnthropicBackend(api_key="test-key")
        assert backend.convert_tools(SAMPLE_TOOLS) is SAMPLE_TOOLS


# ---------------------------------------------------------------------------
# OllamaBackend
# ---------------------------------------------------------------------------

class TestOllamaBackend:
    def _mock_ollama_response(self, content: str | None, tool_calls: list | None = None) -> MagicMock:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "message": {
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls or [],
            }
        }
        return resp

    def test_end_turn_text_response(self) -> None:
        backend = OllamaBackend()
        mock_resp = self._mock_ollama_response("I found it.")

        with patch("requests.post", return_value=mock_resp):
            result = backend.chat("sys", [], SAMPLE_TOOLS)

        assert result.stop_reason == "end_turn"
        assert result.text == "I found it."
        assert result.tool_calls == []

    def test_tool_use_response(self) -> None:
        backend = OllamaBackend()
        raw_tc = {"function": {"name": "search_wiki", "arguments": {"query": "auth"}}}
        mock_resp = self._mock_ollama_response(None, [raw_tc])

        with patch("requests.post", return_value=mock_resp):
            result = backend.chat("sys", [], SAMPLE_TOOLS)

        assert result.stop_reason == "tool_use"
        assert len(result.tool_calls) == 1
        tc = result.tool_calls[0]
        assert tc.name == "search_wiki"
        assert tc.arguments == {"query": "auth"}
        assert tc.id  # generated uuid

    def test_raises_on_non_200(self) -> None:
        backend = OllamaBackend()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "internal error"

        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="Ollama API error 500"):
                backend.chat("sys", [], SAMPLE_TOOLS)

    def test_make_tool_results_messages_one_per_result(self) -> None:
        backend = OllamaBackend()
        tc = ToolCall(id="id1", name="search_wiki", arguments={})
        msgs = backend.make_tool_results_messages([tc], ["result1"])

        assert len(msgs) == 1
        assert msgs[0]["role"] == "tool"
        assert msgs[0]["content"] == "result1"
        assert msgs[0]["name"] == "search_wiki"

    def test_system_prepended_to_messages(self) -> None:
        backend = OllamaBackend()
        mock_resp = self._mock_ollama_response("ok")

        with patch("requests.post", return_value=mock_resp) as mock_post:
            backend.chat("my system", [{"role": "user", "content": "hi"}], [])

        call_body = mock_post.call_args[1]["json"]
        assert call_body["messages"][0] == {"role": "system", "content": "my system"}
        assert call_body["messages"][1] == {"role": "user", "content": "hi"}

    def test_tools_converted_to_openai_format(self) -> None:
        backend = OllamaBackend()
        mock_resp = self._mock_ollama_response("ok")

        with patch("requests.post", return_value=mock_resp) as mock_post:
            backend.chat("sys", [], SAMPLE_TOOLS)

        tools_sent = mock_post.call_args[1]["json"]["tools"]
        assert tools_sent[0]["type"] == "function"
        assert "parameters" in tools_sent[0]["function"]


# ---------------------------------------------------------------------------
# factory.get_backend
# ---------------------------------------------------------------------------

class TestGetBackend:
    def test_anthropic_backend(self, base_cfg: Config) -> None:
        base_cfg.llm_backend = "anthropic"
        backend = get_backend(base_cfg)
        assert isinstance(backend, AnthropicBackend)

    def test_ollama_backend(self, base_cfg: Config) -> None:
        base_cfg.llm_backend = "ollama"
        backend = get_backend(base_cfg)
        assert isinstance(backend, OllamaBackend)
        assert backend.model == base_cfg.ollama_model

    def test_unknown_backend_raises(self, base_cfg: Config) -> None:
        base_cfg.llm_backend = "unknown-llm"
        with pytest.raises(ValueError, match="Unknown llm_backend"):
            get_backend(base_cfg)
