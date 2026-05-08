#!/usr/bin/env python3
# /// script
# dependencies = ["anthropic[vertex]>=0.40", "httpx>=0.27"]
# ///
"""Run a Claude agent defined by a .md file in the agents directory.

Supports two providers:
  - anthropic (default): Uses the Anthropic SDK (Claude Sonnet)
  - ollama: Uses a local Ollama instance via OpenAI-compatible API

Set AGENT_PROVIDER=ollama to use Ollama. Configure with:
  OLLAMA_MODEL    — model name (default: gemma4:31b)
  OLLAMA_BASE_URL — server URL (default: http://localhost:11434)
  OLLAMA_NUM_CTX  — context window size (default: 32768)
"""

import os
import sys
import time
import random

import tools as T
import metrics


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
    {"name": "ReplaceSection", "description": "Replace content between %% section:<name> %% markers in a file. Use this instead of Edit for daily notes and other files with section markers.", "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}, "section": {"type": "string", "description": "Section name (e.g. 'digest', 'conversations', 'meeting-prep')"}, "content": {"type": "string", "description": "New content to place between the markers (include the ### heading)"}}, "required": ["file_path", "section", "content"]}},
]

MAX_TOOL_RESULT_CHARS = 20_000  # prevent runaway context accumulation

TOOL_FN = {
    "Bash": lambda inp: T.bash(inp["command"]),
    "Read": lambda inp: T.read(inp["file_path"], inp.get("offset"), inp.get("limit")),
    "Write": lambda inp: T.write(inp["file_path"], inp["content"]),
    "Edit": lambda inp: T.edit(inp["file_path"], inp["old_string"], inp["new_string"], inp.get("replace_all", False)),
    "Glob": lambda inp: T.glob(inp["pattern"], inp.get("path")),
    "Grep": lambda inp: T.grep(inp["pattern"], inp.get("path"), inp.get("include")),
    "ReplaceSection": lambda inp: T.replace_section(inp["file_path"], inp["section"], inp["content"]),
}


def load_agent(agent_name: str) -> str:
    agent_path = os.path.join(VAULT_DIR, ".claude", "agents", f"{agent_name}.md")
    with open(agent_path, "r") as f:
        content = f.read()
    if content.startswith("---"):
        second_fence = content.index("---", 3)
        content = content[second_fence + 3:]
    return content.strip()


def _run_anthropic(system_prompt: str, prompt: str, agent_name: str):
    """Run the agent loop using the Anthropic SDK (original behavior)."""
    import anthropic

    if os.environ.get("CLAUDE_CODE_USE_VERTEX"):
        client = anthropic.AnthropicVertex(
            project_id=os.environ["ANTHROPIC_VERTEX_PROJECT_ID"],
            region=os.environ.get("ANTHROPIC_VERTEX_REGION", "us-east5"),
        )
    else:
        client = anthropic.Anthropic()

    model = os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "claude-sonnet-4-6[1m]")
    if os.environ.get("CLAUDE_CODE_USE_VERTEX"):
        model = model.split("[")[0]

    m = metrics.RunMetrics(
        agent_name=agent_name,
        provider="vertex" if os.environ.get("CLAUDE_CODE_USE_VERTEX") else "anthropic",
        model=model,
        pipeline_step=os.environ.get("AGENT_PIPELINE_STEP") or None,
        trigger=os.environ.get("AGENT_TRIGGER", "manual"),
    )

    wall_start = time.monotonic()

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

    messages = [{"role": "user", "content": prompt}]
    turns = 0

    try:
        while True:
            turns += 1
            t_api = time.monotonic()
            response = api_call_with_retry(messages)
            api_latency = time.monotonic() - t_api

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
                turn_tool_names = [b.name for b in response.content if b.type == "tool_use"]
                m.record_turn(response, turn_tool_names, api_latency)
                messages.append({"role": "assistant", "content": assistant_content})
                messages.append({"role": "user", "content": tool_results})
            else:
                turn_tool_names = [b.name for b in response.content if b.type == "tool_use"]
                m.record_turn(response, turn_tool_names, api_latency)
                m.finalize(completed=True, stop_reason=response.stop_reason)
                for block in response.content:
                    if hasattr(block, "text"):
                        print(block.text)
                break
    except anthropic.APIError as e:
        m.finalize(completed=False, stop_reason="api_error", error_message=str(e))
        print(f"API error: {e}", file=sys.stderr)
        sys.exit(1)

    total = time.monotonic() - wall_start
    print(f"\n[done] {total:.1f}s total, {turns} turns", file=sys.stderr, flush=True)


def _run_ollama(system_prompt: str, prompt: str, agent_name: str):
    """Run the agent loop using Ollama's native /api/chat endpoint."""
    import json as _json
    import urllib.request
    from adapter.openai_adapter import convert_tools_to_openai, OllamaResponse

    model = os.environ.get("OLLAMA_MODEL", "gemma4:26b")
    num_ctx = int(os.environ.get("OLLAMA_NUM_CTX", "32768"))
    max_tokens = int(os.environ.get("OLLAMA_MAX_TOKENS", "16384"))
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    openai_tools = convert_tools_to_openai(TOOLS)

    m = metrics.RunMetrics(
        agent_name=agent_name,
        provider="ollama",
        model=model,
        pipeline_step=os.environ.get("AGENT_PIPELINE_STEP") or None,
        trigger=os.environ.get("AGENT_TRIGGER", "manual"),
    )

    print(f"[ollama] model={model}, num_ctx={num_ctx}, max_tokens={max_tokens}", file=sys.stderr, flush=True)

    wall_start = time.monotonic()
    ollama_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]
    turns = 0

    try:
        while True:
            turns += 1
            payload = {
                "model": model,
                "messages": ollama_messages,
                "tools": openai_tools,
                "stream": False,
                "think": False,
                "options": {"num_predict": max_tokens, "num_ctx": num_ctx},
            }

            t_api = time.monotonic()
            req = urllib.request.Request(
                f"{base_url}/api/chat",
                data=_json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                raw = _json.load(resp)
            response = OllamaResponse(raw)
            api_latency = time.monotonic() - t_api

            msg = raw.get("message", {})
            tool_calls_raw = msg.get("tool_calls", [])

            if tool_calls_raw:
                ollama_messages.append(msg)

                turn_tool_names = []
                for tc in tool_calls_raw:
                    fn = tc.get("function", {})
                    name = fn.get("name", "")
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        args = _json.loads(args)
                    turn_tool_names.append(name)

                    if name not in TOOL_FN:
                        print(f"[+{time.monotonic()-wall_start:.1f}s] WARN: unknown tool '{name}', skipping", file=sys.stderr, flush=True)
                        ollama_messages.append({"role": "tool", "content": f"Error: unknown tool '{name}'", "tool_name": name})
                        continue

                    t0 = time.monotonic()
                    preview = str(args.get("command") or args.get("file_path") or args.get("pattern") or args)[:80]
                    print(f"[+{time.monotonic()-wall_start:.1f}s] tool: {name}({preview})", file=sys.stderr, flush=True)
                    result = TOOL_FN[name](args)
                    duration = time.monotonic() - t0
                    if len(result) > MAX_TOOL_RESULT_CHARS:
                        result = result[:MAX_TOOL_RESULT_CHARS] + f"\n[... truncated: result was {len(result)} chars, capped at {MAX_TOOL_RESULT_CHARS}]"
                    result_preview = str(result).replace("\n", " ")[:80]
                    print(f"[+{time.monotonic()-wall_start:.1f}s]   -> {duration:.1f}s: {result_preview}", file=sys.stderr, flush=True)
                    ollama_messages.append({"role": "tool", "content": result, "tool_name": name})

                m.record_turn(response, turn_tool_names, api_latency)
            else:
                m.record_turn(response, [], api_latency)
                m.finalize(completed=True, stop_reason=response.stop_reason)
                for block in response.content:
                    if hasattr(block, "text"):
                        print(block.text)
                break
    except Exception as e:
        m.finalize(completed=False, stop_reason="error", error_message=str(e))
        print(f"Ollama error: {e}", file=sys.stderr)
        sys.exit(1)

    total = time.monotonic() - wall_start
    print(f"\n[done] {total:.1f}s total, {turns} turns (ollama/{model})", file=sys.stderr, flush=True)


def main():
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} <agent_name> <prompt>", file=sys.stderr)
        sys.exit(1)

    agent_name = sys.argv[1]
    prompt = " ".join(sys.argv[2:])
    system_prompt = load_agent(agent_name)

    provider = os.environ.get("AGENT_PROVIDER", "anthropic").lower()

    if provider == "ollama":
        _run_ollama(system_prompt, prompt, agent_name)
    else:
        _run_anthropic(system_prompt, prompt, agent_name)


if __name__ == "__main__":
    main()
