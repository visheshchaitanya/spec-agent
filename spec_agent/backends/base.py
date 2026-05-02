from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ChatResponse:
    """Normalized response from any LLM backend."""
    stop_reason: str  # "end_turn" | "tool_use"
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_assistant_turn: dict = field(default_factory=dict)


class LLMBackend(ABC):
    """Abstract base class for LLM backends.

    All backends normalize their API responses to ChatResponse and
    provide helpers to format conversation history in their native
    message format.
    """

    @abstractmethod
    def chat(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 4096,
    ) -> ChatResponse:
        """Send messages to the LLM and return a normalized response.

        Args:
            system: The system prompt.
            messages: Conversation history in this backend's native format.
            tools: Tool definitions in Anthropic schema format (will be
                   converted internally by the backend).
            max_tokens: Maximum tokens to generate.
        """

    @abstractmethod
    def make_user_message(self, content: str) -> dict:
        """Create an initial user message in this backend's format."""

    @abstractmethod
    def make_tool_results_messages(
        self, tool_calls: list[ToolCall], results: list[str]
    ) -> list[dict]:
        """Return messages to append after executing tool calls.

        May return a single message (Anthropic packs all results in one)
        or multiple messages (OpenAI/Ollama sends one per tool result).
        """

    @property
    def max_diff_chars(self) -> int:
        """Max characters of git diff to include in the user message.

        Default is generous (200 KB). Backends with strict TPM limits should
        override this to a lower value.
        """
        return 200_000

    @property
    def ast_budget_chars(self) -> int | None:
        """Max characters allowed for the AST block in the user message.

        Returns None for unlimited (e.g. large-context backends like Anthropic).
        Override in backends with strict token limits.
        """
        return None

    def convert_tools(self, tool_definitions: list[dict]) -> list[dict]:
        """Convert Anthropic-style tool definitions to this backend's format.

        Default implementation returns them unchanged (Anthropic format).
        Override in backends that use a different schema.

        Anthropic format:
            {"name": ..., "description": ..., "input_schema": {...}}

        OpenAI/Ollama format:
            {"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}
        """
        return tool_definitions


def anthropic_to_openai_tools(tool_definitions: list[dict]) -> list[dict]:
    """Convert Anthropic tool schema to OpenAI/Ollama function-calling format."""
    result = []
    for tool in tool_definitions:
        result.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
            },
        })
    return result
