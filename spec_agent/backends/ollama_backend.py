from __future__ import annotations

import uuid
from typing import Any

import requests

from spec_agent.backends.base import (
    ChatResponse,
    LLMBackend,
    ToolCall,
    anthropic_to_openai_tools,
)


class OllamaBackend(LLMBackend):
    """LLM backend that talks to a local Ollama instance via its REST API."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def chat(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 4096,
    ) -> ChatResponse:
        converted_tools = anthropic_to_openai_tools(tools)
        full_messages = [{"role": "system", "content": system}, *messages]

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": full_messages,
            "tools": converted_tools,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }

        resp = requests.post(f"{self.base_url}/api/chat", json=payload)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Ollama API error {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        message: dict[str, Any] = data["message"]
        raw_tool_calls: list[dict] = message.get("tool_calls") or []

        tool_calls = [
            ToolCall(
                id=tc.get("id") or str(uuid.uuid4()),
                name=tc["function"]["name"],
                arguments=tc["function"]["arguments"],
            )
            for tc in raw_tool_calls
        ]

        stop_reason = "tool_use" if tool_calls else "end_turn"

        return ChatResponse(
            stop_reason=stop_reason,
            text=message.get("content") or None,
            tool_calls=tool_calls,
            raw_assistant_turn=message,
        )

    def make_user_message(self, content: str) -> dict:
        return {"role": "user", "content": content}

    def make_tool_results_messages(
        self, tool_calls: list[ToolCall], results: list[str]
    ) -> list[dict]:
        return [
            {"role": "tool", "content": result, "name": tc.name}
            for tc, result in zip(tool_calls, results)
        ]

    def convert_tools(self, tool_definitions: list[dict]) -> list[dict]:
        return anthropic_to_openai_tools(tool_definitions)
