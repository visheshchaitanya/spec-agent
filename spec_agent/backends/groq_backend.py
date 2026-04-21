from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests

from spec_agent.backends.base import (
    ChatResponse,
    LLMBackend,
    ToolCall,
    anthropic_to_openai_tools,
)

logger = logging.getLogger(__name__)


class GroqBackend(LLMBackend):
    """LLM backend that routes calls through Groq Cloud (OpenAI-compatible API).

    Free tier: 30 RPM, 1 000 RPD, 12 000 TPM, 100 000 TPD for llama-3.3-70b-versatile.
    See https://console.groq.com/docs/rate-limits for current limits.
    """

    BASE_URL = "https://api.groq.com/openai/v1"

    def __init__(self, model: str = "llama-3.3-70b-versatile") -> None:
        self.model = model

    def chat(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 4096,
    ) -> ChatResponse:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GROQ_API_KEY environment variable is not set. "
                "Get a free key at https://console.groq.com and export it:\n"
                '  export GROQ_API_KEY="gsk_..."'
            )

        converted_tools = anthropic_to_openai_tools(tools)

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "max_tokens": max_tokens,
        }
        if converted_tools:
            payload["tools"] = converted_tools

        resp = requests.post(
            f"{self.BASE_URL}/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=120,
        )

        if resp.status_code == 429:
            raise RuntimeError(
                "Groq rate limit exceeded. Free tier: 30 RPM / 1 000 RPD for llama-3.3-70b-versatile. "
                "See https://console.groq.com/docs/rate-limits for current limits."
            )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Groq API error {resp.status_code}: {resp.text}"
            )

        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"Groq returned empty choices: {data}")

        message = choices[0]["message"]

        raw_tool_calls = message.get("tool_calls") or []
        tool_calls: list[ToolCall] = []
        for tc in raw_tool_calls:
            try:
                arguments = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, KeyError) as e:
                raise RuntimeError(
                    f"Failed to parse tool call arguments: {e}\nRaw: {tc}"
                )
            tool_calls.append(
                ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=arguments,
                )
            )

        finish_reason = choices[0].get("finish_reason")
        if finish_reason == "tool_calls":
            stop_reason = "tool_use"
        elif finish_reason == "length":
            logger.warning(
                "Groq response truncated by max_tokens (finish_reason=length)"
            )
            stop_reason = "end_turn"
        else:
            stop_reason = "end_turn"

        raw_assistant_turn: dict[str, Any] = {
            "role": "assistant",
            "content": message.get("content"),
        }
        if tool_calls:
            raw_assistant_turn["tool_calls"] = [
                {
                    "id": tc_data.id,
                    "type": "function",
                    "function": {
                        "name": tc_data.name,
                        "arguments": json.dumps(tc_data.arguments),
                    },
                }
                for tc_data in tool_calls
            ]

        return ChatResponse(
            stop_reason=stop_reason,
            text=message.get("content") or None,
            tool_calls=tool_calls,
            raw_assistant_turn=raw_assistant_turn,
        )

    def make_user_message(self, content: str) -> dict:
        return {"role": "user", "content": content}

    def make_tool_results_messages(
        self, tool_calls: list[ToolCall], results: list[str]
    ) -> list[dict]:
        return [
            {"role": "tool", "tool_call_id": tc.id, "content": result}
            for tc, result in zip(tool_calls, results, strict=True)
        ]

    def convert_tools(self, tool_definitions: list[dict]) -> list[dict]:
        return anthropic_to_openai_tools(tool_definitions)
