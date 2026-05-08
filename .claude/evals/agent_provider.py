"""Promptfoo Python provider that runs a multi-turn agent tool-calling loop.

Emulates the real run_agent.py pipeline: loads the agent system prompt,
sends it with tools to the model, executes tool calls against mock data,
and loops until the model produces a final text response.

Config options (passed via provider config in YAML):
  agent: agent name (e.g., "conversation-summarizer")
  model: ollama model name (default: gemma4:26b)
  think: enable thinking (default: false)
  max_turns: max tool-calling turns (default: 20)
  num_ctx: context window (default: 32768)
  num_predict: max output tokens (default: 16384)
  mock_dir: path to fixtures directory for mock tool results
"""

import json
import os
import re
import sys
import time
from pathlib import Path

VAULT_DIR = os.environ.get("VAULT_DIR", str(Path(__file__).resolve().parents[2]))
SCRIPTS_DIR = str(Path(__file__).resolve().parent.parent / "skills" / "daily-sync-all" / "scripts")

sys.path.insert(0, SCRIPTS_DIR)
from adapter.openai_adapter import (
    convert_tools_to_openai,
    build_openai_messages,
)

TOOLS = [
    {"name": "Bash", "description": "Run a shell command", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}, "description": {"type": "string"}}, "required": ["command"]}},
    {"name": "Read", "description": "Read a file", "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}, "offset": {"type": "integer"}, "limit": {"type": "integer"}}, "required": ["file_path"]}},
    {"name": "Write", "description": "Write a file", "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}, "content": {"type": "string"}}, "required": ["file_path", "content"]}},
    {"name": "Edit", "description": "Edit a file", "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"}, "replace_all": {"type": "boolean"}}, "required": ["file_path", "old_string", "new_string"]}},
    {"name": "Glob", "description": "Find files by pattern", "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}}, "required": ["pattern"]}},
    {"name": "Grep", "description": "Search file contents", "input_schema": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}, "include": {"type": "string"}}, "required": ["pattern"]}},
]


def load_agent(agent_name: str) -> str:
    agent_path = os.path.join(VAULT_DIR, ".claude", "agents", f"{agent_name}.md")
    with open(agent_path, "r") as f:
        content = f.read()
    if content.startswith("---"):
        second_fence = content.index("---", 3)
        content = content[second_fence + 3:]
    return content.strip()


def mock_tool(name: str, inp: dict, mock_dir: str, files_state: dict) -> str:
    """Execute a tool call against mock fixtures.

    For Read: looks up file in mock_dir/fixtures/ or files_state (for writes).
    For Glob: returns matching files from mock_dir/fixtures/.
    For Bash: returns canned responses for common commands.
    For Write/Edit: updates files_state in memory.
    For Grep: does a basic search through files_state.
    """
    fixtures_dir = Path(mock_dir)

    if name == "Read":
        file_path = inp.get("file_path", "")
        basename = Path(file_path).name

        # Check in-memory state first (for files written/edited during the session)
        if file_path in files_state:
            content = files_state[file_path]
            lines = content.split("\n")
            offset = (inp.get("offset", 1) or 1) - 1
            limit = inp.get("limit") or 100
            numbered = []
            for i, line in enumerate(lines[offset:offset+limit], start=offset+1):
                numbered.append(f"  {i}\t{line}")
            return "\n".join(numbered)

        # Check fixtures
        fixture_path = fixtures_dir / basename
        if fixture_path.exists():
            content = fixture_path.read_text()
            files_state[file_path] = content
            lines = content.split("\n")
            offset = (inp.get("offset", 1) or 1) - 1
            limit = inp.get("limit") or 100
            numbered = []
            for i, line in enumerate(lines[offset:offset+limit], start=offset+1):
                numbered.append(f"  {i}\t{line}")
            return "\n".join(numbered)

        return f"Error: file not found: {file_path}"

    elif name == "Glob":
        pattern = inp.get("pattern", "")
        # Return fixture filenames that match
        matches = []
        for f in sorted(fixtures_dir.glob("*")):
            if f.is_file() and f.suffix == ".md":
                matches.append(str(f.name))
        # Also check files_state
        for path in sorted(files_state.keys()):
            basename = Path(path).name
            if basename not in [Path(m).name for m in matches]:
                matches.append(path)
        return "\n".join(matches) if matches else "No matches found"

    elif name == "Grep":
        pattern = inp.get("pattern", "")
        results = []
        for path, content in files_state.items():
            for i, line in enumerate(content.split("\n"), 1):
                if re.search(pattern, line, re.IGNORECASE):
                    results.append(f"{path}:{i}: {line}")
                    if len(results) >= 20:
                        return "\n".join(results)
        return "\n".join(results) if results else "No matches found"

    elif name == "Bash":
        command = inp.get("command", "")
        if "date" in command:
            return "2026-05-07"
        elif "obsidian" in command and "version" in command:
            return "Obsidian v1.12.0"
        elif "obsidian" in command and "daily:path" in command:
            return "daily/2026/05-May/2026-05-07-Thursday.md"
        elif "sqlite3" in command:
            return "No results found"
        elif "pkm-sync" in command:
            return "[]"
        return f"Command executed: {command[:80]}"

    elif name == "Write":
        file_path = inp.get("file_path", "")
        content = inp.get("content", "")
        files_state[file_path] = content
        return f"Written: {file_path}"

    elif name == "Edit":
        file_path = inp.get("file_path", "")
        old_string = inp.get("old_string", "")
        new_string = inp.get("new_string", "")
        if file_path not in files_state:
            return f"Error: file not found: {file_path}"
        content = files_state[file_path]
        if old_string not in content:
            return f"Error: old_string not found in {file_path}"
        files_state[file_path] = content.replace(old_string, new_string, 1)
        return f"Edited: {file_path}"

    return f"Error: unknown tool: {name}"


def _build_output(chat_message: str, files_state: dict) -> str:
    """Combine the agent's chat response with the content of all written/edited files.

    This lets assertions check what the agent actually produced (file content)
    rather than just the status message it reported in chat.
    """
    parts = []
    if chat_message.strip():
        parts.append(f"--- AGENT MESSAGE ---\n{chat_message.strip()}")
    for path in sorted(files_state.keys()):
        content = files_state[path]
        parts.append(f"--- FILE: {path} ---\n{content}")
    return "\n\n".join(parts)


def call_api(prompt, options, context):
    """Promptfoo Python provider entry point."""
    config = options.get("config", {})
    agent_name = config.get("agent", "conversation-summarizer")
    model = config.get("model", "gemma4:26b")
    think = config.get("think", False)
    max_turns = config.get("max_turns", 20)
    num_ctx = config.get("num_ctx", 32768)
    num_predict = config.get("num_predict", 16384)
    mock_dir = config.get("mock_dir", str(Path(__file__).parent / "fixtures"))

    openai_tools = convert_tools_to_openai(TOOLS)

    # Parse prompt — may be a JSON chat array or plain string
    try:
        messages_raw = json.loads(prompt)
        if isinstance(messages_raw, list):
            user_msg = messages_raw[-1].get("content", prompt)
        else:
            user_msg = prompt
    except (json.JSONDecodeError, TypeError):
        user_msg = prompt

    # Extract agent name from context vars (fallback to config)
    ctx_vars = context.get("vars", {})
    agent_name = ctx_vars.get("agent", config.get("agent", "conversation-summarizer"))
    system_prompt = load_agent(agent_name)

    # Use Ollama native message format (not OpenAI-compat)
    ollama_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]
    files_state = {}
    wall_start = time.monotonic()
    turns = 0
    tool_calls_log = []
    total_prompt_tokens = 0
    total_completion_tokens = 0

    import urllib.request
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

    try:
        while turns < max_turns:
            turns += 1

            payload = {
                "model": model,
                "messages": ollama_messages,
                "tools": openai_tools,
                "stream": False,
                "think": think,
                "options": {
                    "num_predict": num_predict,
                    "num_ctx": num_ctx,
                },
            }

            req = urllib.request.Request(
                f"{base_url}/api/chat",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = json.load(resp)

            msg = data.get("message", {})
            total_prompt_tokens += data.get("prompt_eval_count", 0)
            total_completion_tokens += data.get("eval_count", 0)

            content = msg.get("content", "")
            tool_calls_raw = msg.get("tool_calls", [])

            if tool_calls_raw:
                # Append assistant message with tool_calls (Ollama native format)
                ollama_messages.append(msg)

                # Execute each tool and append results
                for tc in tool_calls_raw:
                    fn = tc.get("function", {})
                    args = fn.get("arguments", {})
                    if isinstance(args, str):
                        args = json.loads(args)

                    result = mock_tool(fn["name"], args, mock_dir, files_state)
                    tool_calls_log.append({
                        "turn": turns,
                        "tool": fn["name"],
                        "input": args,
                        "result_len": len(result),
                    })
                    # Ollama native tool result format
                    ollama_messages.append({
                        "role": "tool",
                        "content": result[:20000],
                        "tool_name": fn["name"],
                    })
            else:
                # Final response — no more tool calls
                wall_time = time.monotonic() - wall_start
                output = _build_output(content, files_state)
                return {
                    "output": output,
                    "tokenUsage": {
                        "prompt": total_prompt_tokens,
                        "completion": total_completion_tokens,
                        "total": total_prompt_tokens + total_completion_tokens,
                    },
                    "metadata": {
                        "turns": turns,
                        "tool_calls": len(tool_calls_log),
                        "wall_time_s": round(wall_time, 1),
                        "model": model,
                        "think": think,
                        "files_written": list(files_state.keys()),
                        "tool_log": tool_calls_log[:10],
                    },
                }

        # Hit max turns
        wall_time = time.monotonic() - wall_start
        output = _build_output("", files_state)
        return {
            "output": output or f"[Agent reached max_turns={max_turns} without final response]",
            "tokenUsage": {
                "prompt": total_prompt_tokens,
                "completion": total_completion_tokens,
                "total": total_prompt_tokens + total_completion_tokens,
            },
            "metadata": {
                "turns": turns,
                "tool_calls": len(tool_calls_log),
                "wall_time_s": round(wall_time, 1),
                "model": model,
                "think": think,
                "hit_max_turns": True,
                "files_written": list(files_state.keys()),
                "tool_log": tool_calls_log[:10],
            },
        }

    except Exception as e:
        return {
            "error": f"Agent error after {turns} turns: {e}",
            "tokenUsage": {
                "prompt": total_prompt_tokens,
                "completion": total_completion_tokens,
                "total": total_prompt_tokens + total_completion_tokens,
            },
        }
