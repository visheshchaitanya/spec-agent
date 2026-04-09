from __future__ import annotations

import os
import uuid
from typing import Any

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError as exc:
    raise ImportError(
        "The 'google-genai' package is required for GeminiBackend. "
        "Install it with: pip install google-genai"
    ) from exc

from spec_agent.backends.base import ChatResponse, LLMBackend, ToolCall


class GeminiBackend(LLMBackend):
    """LLM backend that calls the Google Gemini API via the google-genai SDK."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gemini-2.0-flash",
    ) -> None:
        resolved_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not resolved_key:
            raise ValueError(
                "A Gemini API key is required. Pass api_key= or set GEMINI_API_KEY."
            )
        self.model = model
        self._client = genai.Client(api_key=resolved_key)

    def _build_gemini_tools(
        self, tool_definitions: list[dict]
    ) -> list[genai_types.Tool]:
        declarations = [
            genai_types.FunctionDeclaration(
                name=tool["name"],
                description=tool.get("description", ""),
                parameters=tool.get("input_schema", {"type": "object", "properties": {}}),
            )
            for tool in tool_definitions
        ]
        return [genai_types.Tool(function_declarations=declarations)]

    def _convert_messages(
        self, messages: list[dict]
    ) -> list[genai_types.Content]:
        contents: list[genai_types.Content] = []
        for msg in messages:
            role = msg.get("role", "")

            if role == "tool_result":
                parts = [
                    genai_types.Part.from_function_response(
                        name=tr["name"],
                        response={"result": tr["result"]},
                    )
                    for tr in msg.get("tool_results", [])
                ]
                contents.append(genai_types.Content(role="user", parts=parts))

            elif role in ("assistant", "model"):
                content_text: str = msg.get("content") or ""
                contents.append(
                    genai_types.Content(
                        role="model",
                        parts=[genai_types.Part.from_text(text=content_text)],
                    )
                )

            else:  # "user" or anything else
                content_text = msg.get("content") or ""
                contents.append(
                    genai_types.Content(
                        role="user",
                        parts=[genai_types.Part.from_text(text=content_text)],
                    )
                )

        return contents

    def chat(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 4096,
    ) -> ChatResponse:
        gemini_tools = self._build_gemini_tools(tools)
        contents = self._convert_messages(messages)

        config = genai_types.GenerateContentConfig(
            system_instruction=system,
            tools=gemini_tools,
            max_output_tokens=max_tokens,
        )

        response = self._client.models.generate_content(
            model=self.model,
            contents=contents,
            config=config,
        )

        parts = response.candidates[0].content.parts

        tool_calls: list[ToolCall] = []
        text: str | None = None

        for part in parts:
            if hasattr(part, "function_call") and part.function_call is not None:
                fc = part.function_call
                tool_calls.append(
                    ToolCall(
                        id=str(uuid.uuid4()),
                        name=fc.name,
                        arguments=dict(fc.args),
                    )
                )
            elif hasattr(part, "text") and part.text and text is None:
                text = part.text

        stop_reason = "tool_use" if tool_calls else "end_turn"
        raw_assistant_turn: dict[str, Any] = {
            "role": "model",
            "content": text or "",
            "tool_calls": [
                {"name": tc.name, "arguments": tc.arguments} for tc in tool_calls
            ],
        }

        return ChatResponse(
            stop_reason=stop_reason,
            text=text,
            tool_calls=tool_calls,
            raw_assistant_turn=raw_assistant_turn,
        )

    def make_user_message(self, content: str) -> dict:
        return {"role": "user", "content": content}

    def make_tool_results_messages(
        self, tool_calls: list[ToolCall], results: list[str]
    ) -> list[dict]:
        return [
            {
                "role": "tool_result",
                "tool_results": [
                    {"name": tc.name, "result": result}
                    for tc, result in zip(tool_calls, results)
                ],
            }
        ]

    def convert_tools(self, tool_definitions: list[dict]) -> list[dict]:
        return tool_definitions
