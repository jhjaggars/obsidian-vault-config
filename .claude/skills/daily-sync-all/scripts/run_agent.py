#!/usr/bin/env python3
# /// script
# dependencies = ["anthropic[vertex]>=0.40"]
# ///
"""Run a Claude agent defined by a .md file in the agents directory."""

import os
import sys
import time
import random

import anthropic

import tools as T


def _find_vault_root() -> str:
    """Walk up from this script's location to find the vault root (has .obsidian/)."""
    from pathlib import Path
    for parent in Path(__file__).resolve().parents:
        if (parent / ".obsidian").is_dir():
            return str(parent)
    raise RuntimeError(f"Could not find vault root (no .obsidian/ dir above {__file__})")


VAULT_DIR = os.environ.get("VAULT_DIR") or _find_vault_root()

TOOLS = [
    {"name": "Bash", "description": "Run a shell command", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}, "description": {"type": "string"}}, "required": ["command"]}},
    {"name": "Read", "description": "Read a file", "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["file_path"]}},
    {"name": "Write", "description": "Write a file", "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["file_path", "content"]}},
    {"name": "Edit", "description": "Edit a file", "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}, "replace_all": {"type": "boolean"}}, "required": ["file_path", "old_string", "new_string"]}},
    {"name": "Glob", "description": "Find files by pattern", "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}}, "required": ["pattern"]}},
    {"name": "Grep", "description": "Search file contents", "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}, "include": {"type": "string"}}, "required": ["pattern"]}},
]

MAX_TOOL_RESULT_CHARS = 20_000  # prevent runaway context accumulation

TOOL_FN = {
    "Bash": lambda inp: T.bash(inp["command"]),
    "Read": lambda inp: T.read(inp["file_path"], inp.get("offset"), inp.get("limit")),
    "Write": lambda inp: T.write(inp["file_path"], inp["content"]),
    "Edit": lambda inp: T.edit(inp["file_path"], inp["old_string"], inp["new_string"], inp.get("replace_all", False)),
    "Glob": lambda inp: T.glob(inp["pattern"], inp.get("path")),
    "Grep": lambda inp: T.grep(inp["pattern"], inp.get("path"), inp.get("include")),
}


def load_agent(agent_name: str) -> str:
    agent_path = os.path.join(VAULT_DIR, ".claude", "agents", f"{agent_name}.md")
    with open(agent_path, "r") as f:
        content = f.read()
    if content.startswith("---"):
        second_fence = content.index("---", 3)
        content = content[second_fence + 3:]
    return content.strip()


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <agent_name> <prompt>", file=sys.stderr)
        sys.exit(1)

    agent_name = sys.argv[1]
    prompt = " ".join(sys.argv[2:])
    system_prompt = load_agent(agent_name)

    if os.environ.get("CLAUDE_CODE_USE_VERTEX"):
        client = anthropic.AnthropicVertex(
            project_id=os.environ["ANTHROPIC_VERTEX_PROJECT_ID"],
            region=os.environ.get("ANTHROPIC_VERTEX_REGION", "us-east5"),
        )
    else:
        client = anthropic.Anthropic()

    model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-6[1m]")
    # Vertex AI endpoint names don't support bracketed suffixes like [1m]
    if os.environ.get("CLAUDE_CODE_USE_VERTEX"):
        model = model.split("[")[0]

    def api_call_with_retry(messages):
        max_retries = 4
        base_delay = 10
        for attempt in range(max_retries + 1):
            try:
                return client.messages.create(
                    model=model,
                    max_tokens=8096,
                    system=system_prompt,
                    tools=TOOLS,
                    messages=messages,
                )
            except (anthropic.RateLimitError, anthropic.APIStatusError) as e:
                status = getattr(e, "status_code", None)
                retryable = isinstance(e, anthropic.RateLimitError) or status in (429, 529, 500, 502, 503, 504)
                if retryable and attempt < max_retries:
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 2)
                    print(f"[+{time.monotonic()-wall_start:.1f}s] API error ({status or 'rate_limit'}), retry {attempt+1}/{max_retries} in {delay:.1f}s", file=sys.stderr, flush=True)
                    time.sleep(delay)
                else:
                    raise

    wall_start = time.monotonic()
    messages = [{"role": "user", "content": prompt}]
    turns = 0

    try:
        while True:
            turns += 1
            response = api_call_with_retry(messages)

            if response.stop_reason == "tool_use":
                tool_results = []
                assistant_content = []
                for b in response.content:
                    if b.type == "text":
                        assistant_content.append({"type": "text", "text": b.text})
                    elif b.type == "tool_use":
                        assistant_content.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
                for block in response.content:
                    if block.type == "tool_use":
                        t0 = time.monotonic()
                        inp = block.input
                        name = block.name
                        preview = str(inp.get("command") or inp.get("file_path") or inp.get("pattern") or inp)[:80]
                        print(f"[+{time.monotonic()-wall_start:.1f}s] tool: {name}({preview})", file=sys.stderr, flush=True)
                        result = TOOL_FN[name](inp)
                        duration = time.monotonic() - t0
                        if len(result) > MAX_TOOL_RESULT_CHARS:
                            result = result[:MAX_TOOL_RESULT_CHARS] + f"\n[... truncated: result was {len(result)} chars, capped at {MAX_TOOL_RESULT_CHARS}]"
                        result_preview = str(result).replace("\n", " ")[:80]
                        print(f"[+{time.monotonic()-wall_start:.1f}s]   -> {duration:.1f}s: {result_preview}", file=sys.stderr, flush=True)
                        tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
                messages.append({"role": "assistant", "content": assistant_content})
                messages.append({"role": "user", "content": tool_results})
            else:
                for block in response.content:
                    if hasattr(block, "text"):
                        print(block.text)
                break
    except anthropic.APIError as e:
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(1)

    total = time.monotonic() - wall_start
    print(f"\n[done] {total:.1f}s total, {turns} turns", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
