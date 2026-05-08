"""Adapter to run agent tool-use loops via Ollama's OpenAI-compatible API.

Translates between the Anthropic tool schema used by run_agent.py and the
OpenAI function-calling format that Ollama serves at /v1/chat/completions.
"""

import json
import os
from typing import Any


def convert_tools_to_openai(anthropic_tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool definitions to OpenAI function-calling format.

    Anthropic: {"name": ..., "description": ..., "input_schema": {...}}
    OpenAI:    {"type": "function", "function": {"name": ..., "description": ..., "parameters": {...}}}
    """
    openai_tools = []
    for tool in anthropic_tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        })
    return openai_tools


def build_openai_messages(system_prompt: str, anthropic_messages: list[dict]) -> list[dict]:
    """Convert Anthropic-style messages to OpenAI chat format.

    Handles:
    - System prompt → {"role": "system", ...}
    - User text messages
    - Assistant messages with tool_use blocks
    - Tool result messages
    """
    messages = [{"role": "system", "content": system_prompt}]

    for msg in anthropic_messages:
        role = msg["role"]

        if role == "user":
            content = msg["content"]
            if isinstance(content, str):
                messages.append({"role": "user", "content": content})
            elif isinstance(content, list):
                # Could be tool_result blocks
                tool_results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
                if tool_results:
                    for tr in tool_results:
                        tool_content = tr.get("content", "")
                        if isinstance(tool_content, list):
                            tool_content = "\n".join(
                                b.get("text", str(b)) for b in tool_content
                            )
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tr["tool_use_id"],
                            "content": str(tool_content),
                        })
                else:
                    text_parts = [
                        b.get("text", str(b)) if isinstance(b, dict) else str(b)
                        for b in content
                    ]
                    messages.append({"role": "user", "content": "\n".join(text_parts)})

        elif role == "assistant":
            content = msg["content"]
            if isinstance(content, str):
                messages.append({"role": "assistant", "content": content})
            elif isinstance(content, list):
                text_parts = []
                tool_calls = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block["text"])
                        elif block.get("type") == "tool_use":
                            tool_calls.append({
                                "id": block["id"],
                                "type": "function",
                                "function": {
                                    "name": block["name"],
                                    "arguments": json.dumps(block["input"]),
                                },
                            })
                assistant_msg: dict[str, Any] = {"role": "assistant"}
                if text_parts:
                    assistant_msg["content"] = "\n".join(text_parts)
                else:
                    assistant_msg["content"] = None
                if tool_calls:
                    assistant_msg["tool_calls"] = tool_calls
                messages.append(assistant_msg)

    return messages


class OllamaResponse:
    """Normalized response matching the interface run_agent.py expects.

    Handles both native Ollama (/api/chat) and OpenAI-compat (/v1/chat/completions)
    response formats.
    """

    def __init__(self, raw_response: dict):
        self._raw = raw_response
        self.usage = _OllamaUsage(raw_response)

        # Native Ollama format: {"message": {...}, "done_reason": "stop"}
        # OpenAI-compat format: {"choices": [{"message": {...}, "finish_reason": "stop"}]}
        if "choices" in raw_response:
            choice = raw_response["choices"][0]
            message = choice.get("message", {})
            finish_reason = choice.get("finish_reason", "stop")
        else:
            message = raw_response.get("message", {})
            finish_reason = raw_response.get("done_reason", "stop")

        self.stop_reason = self._normalize_stop_reason(finish_reason, message)
        self.content = self._build_content_blocks(message)

    @staticmethod
    def _normalize_stop_reason(finish_reason: str, message: dict) -> str:
        if finish_reason == "tool_calls" or message.get("tool_calls"):
            return "tool_use"
        return "end_turn"

    @staticmethod
    def _build_content_blocks(message: dict) -> list:
        blocks = []

        text = message.get("content")
        if text:
            blocks.append(_TextBlock(text))

        for tc in message.get("tool_calls", []):
            fn = tc.get("function", {})
            raw_args = fn.get("arguments", {})
            if isinstance(raw_args, dict):
                args = raw_args
            elif isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {"_raw_arguments": raw_args}
            else:
                args = {}
            blocks.append(_ToolUseBlock(
                id=tc.get("id", ""),
                name=fn.get("name", ""),
                input=args,
            ))

        return blocks


class _OllamaUsage:
    """Token and timing data from Ollama's native response."""

    def __init__(self, raw: dict):
        self.input_tokens = raw.get("prompt_eval_count", 0)
        self.output_tokens = raw.get("eval_count", 0)
        self.cache_read_input_tokens = 0
        self.cache_creation_input_tokens = 0
        self.thinking_tokens = 0
        self.eval_duration_ns = raw.get("eval_duration")
        self.prompt_eval_duration_ns = raw.get("prompt_eval_duration")
        self.total_duration_ns = raw.get("total_duration")
        self.load_duration_ns = raw.get("load_duration")


class _TextBlock:
    def __init__(self, text: str):
        self.type = "text"
        self.text = text


class _ToolUseBlock:
    def __init__(self, id: str, name: str, input: dict):
        self.type = "tool_use"
        self.id = id
        self.name = name
        self.input = input


def create_ollama_client():
    """Create an httpx-based client for Ollama's OpenAI-compatible endpoint."""
    try:
        import httpx
    except ImportError:
        raise ImportError(
            "httpx is required for Ollama support. "
            "Add 'httpx' to your script dependencies."
        )

    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    return _OllamaClient(base_url, httpx)


class _OllamaClient:
    """Minimal client wrapping Ollama's /v1/chat/completions endpoint."""

    def __init__(self, base_url: str, httpx_mod):
        self.base_url = base_url.rstrip("/")
        self.httpx = httpx_mod

    def chat_completion(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = 8096,
        num_ctx: int | None = None,
    ) -> OllamaResponse:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_predict": max_tokens,
            },
        }
        if num_ctx:
            payload["options"]["num_ctx"] = num_ctx
        if tools:
            payload["tools"] = tools

        # Use native Ollama endpoint (not OpenAI-compat) for think support
        payload["think"] = False
        url = f"{self.base_url}/api/chat"
        with self.httpx.Client(timeout=300) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            return OllamaResponse(resp.json())
