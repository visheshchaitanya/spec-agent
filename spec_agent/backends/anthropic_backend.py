from __future__ import annotations

import os

import anthropic

from spec_agent.backends.base import ChatResponse, LLMBackend, ToolCall


class AnthropicBackend(LLMBackend):
    """LLM backend for the Anthropic Messages API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-6",
    ) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model

    def chat(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 4096,
    ) -> ChatResponse:
        client = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            tools=self.convert_tools(tools),
            messages=messages,
        )

        stop_reason = (
            response.stop_reason
            if response.stop_reason in ("end_turn", "tool_use")
            else "end_turn"
        )

        text: str | None = None
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text" and text is None:
                text = block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=block.input)
                )

        return ChatResponse(
            stop_reason=stop_reason,
            text=text,
            tool_calls=tool_calls,
            raw_assistant_turn={"role": "assistant", "content": response.content},
        )

    def make_user_message(self, content: str) -> dict:
        return {"role": "user", "content": content}

    def make_tool_results_messages(
        self, tool_calls: list[ToolCall], results: list[str]
    ) -> list[dict]:
        return [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": result,
                    }
                    for tc, result in zip(tool_calls, results)
                ],
            }
        ]

    def convert_tools(self, tool_definitions: list[dict]) -> list[dict]:
        return tool_definitions
