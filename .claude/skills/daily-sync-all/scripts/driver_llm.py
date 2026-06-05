"""Shared LLM calling logic for hybrid driver scripts.

Provides a single `call_llm()` function that handles both Ollama and Anthropic,
executes tool calls, and records metrics. Used by project_update_driver.py and
dossier_driver.py to avoid duplicating LLM + metrics plumbing.
"""

import json
import os
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import metrics
import tools as T
from adapter.openai_adapter import convert_tools_to_openai, OllamaResponse

# Default tools available to drivers
TOOLS_SCHEMA = [
    {"name": "ReplaceSection", "description": "Replace content between %% section:<name> %% markers in a file.",
     "input_schema": {"type": "object", "properties": {
         "file_path": {"type": "string"}, "section": {"type": "string"},
         "content": {"type": "string"}}, "required": ["file_path", "section", "content"]}},
    {"name": "Edit", "description": "Edit a file with old/new string replacement.",
     "input_schema": {"type": "object", "properties": {
         "file_path": {"type": "string"}, "old_string": {"type": "string"},
         "new_string": {"type": "string"}}, "required": ["file_path", "old_string", "new_string"]}},
    {"name": "Read", "description": "Read a file.",
     "input_schema": {"type": "object", "properties": {
         "file_path": {"type": "string"}}, "required": ["file_path"]}},
]

TOOL_FN = {
    "ReplaceSection": lambda a: T.replace_section(a["file_path"], a["section"], a["content"]),
    "Edit": lambda a: T.edit(a["file_path"], a["old_string"], a["new_string"]),
    "Read": lambda a: T.read(a["file_path"]),
}


def call_llm(
    system_prompt: str,
    user_prompt: str,
    agent_name: str,
    item_label: str,
    max_turns: int = 10,
) -> bool:
    """Call the LLM with tools, execute tool calls, record metrics. Returns True if a write occurred."""
    provider = os.environ.get("AGENT_PROVIDER", "anthropic").lower()
    if provider == "ollama":
        return _call_ollama(system_prompt, user_prompt, agent_name, item_label, max_turns)
    else:
        return _call_anthropic(system_prompt, user_prompt, agent_name, item_label, max_turns)


def call_llm_batch(
    system_prompt: str,
    user_prompt: str,
    agent_name: str,
    item_label: str,
) -> str:
    """Call the LLM WITHOUT tools. Returns the raw text response.

    Used for mega-prompt / prompt-stuffing patterns where all data is
    pre-gathered in Python and we just need the LLM to synthesize text.
    """
    provider = os.environ.get("AGENT_PROVIDER", "anthropic").lower()
    if provider == "ollama":
        return _call_ollama_batch(system_prompt, user_prompt, agent_name, item_label)
    else:
        return _call_anthropic_batch(system_prompt, user_prompt, agent_name, item_label)


def _call_ollama_batch(
    system_prompt: str, user_prompt: str,
    agent_name: str, item_label: str,
) -> str:
    import urllib.request

    model = os.environ.get("OLLAMA_MODEL", "granite4.1:8b")
    num_ctx = int(os.environ.get("OLLAMA_NUM_CTX", "131072"))
    max_tokens = int(os.environ.get("OLLAMA_MAX_TOKENS", "8192"))
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

    m = metrics.RunMetrics(
        agent_name=agent_name,
        provider="ollama",
        model=model,
        model_variant=item_label,
        pipeline_step=os.environ.get("AGENT_PIPELINE_STEP"),
        trigger=os.environ.get("AGENT_TRIGGER", "scheduled"),
    )

    t_api = time.monotonic()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "think": False,
        "options": {"num_predict": max_tokens, "num_ctx": num_ctx, "temperature": 0},
    }
    try:
        req = urllib.request.Request(
            f"{base_url}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=600) as resp:
            raw = json.load(resp)
        api_latency = time.monotonic() - t_api

        response = OllamaResponse(raw)
        m.record_turn(response, [], api_latency)
        m.finalize(completed=True, stop_reason="stop")

        text = raw.get("message", {}).get("content", "")
        return text
    except Exception as e:
        m.finalize(completed=False, stop_reason="error", error_message=str(e))
        raise


def _call_anthropic_batch(
    system_prompt: str, user_prompt: str,
    agent_name: str, item_label: str,
) -> str:
    import anthropic

    if os.environ.get("CLAUDE_CODE_USE_VERTEX"):
        client = anthropic.AnthropicVertex(
            project_id=os.environ["ANTHROPIC_VERTEX_PROJECT_ID"],
            region=os.environ.get("ANTHROPIC_VERTEX_REGION", "us-east5"),
        )
    else:
        client = anthropic.Anthropic()

    model = os.environ.get("DAILY_SYNC_MODEL") \
        or os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL") \
        or "claude-haiku-4-5"
    if os.environ.get("CLAUDE_CODE_USE_VERTEX"):
        model = model.split("[")[0]

    m = metrics.RunMetrics(
        agent_name=agent_name,
        provider="vertex" if os.environ.get("CLAUDE_CODE_USE_VERTEX") else "anthropic",
        model=model,
        model_variant=item_label,
        pipeline_step=os.environ.get("AGENT_PIPELINE_STEP"),
        trigger=os.environ.get("AGENT_TRIGGER", "scheduled"),
    )

    try:
        max_tokens = int(os.environ.get("LLM_BATCH_MAX_TOKENS", "16384"))

        t_api = time.monotonic()
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        api_latency = time.monotonic() - t_api

        m.record_turn(response, [], api_latency)
        m.finalize(completed=True, stop_reason=response.stop_reason)

        text = "".join(b.text for b in response.content if hasattr(b, "text"))
        return text
    except Exception as e:
        m.finalize(completed=False, stop_reason="error", error_message=str(e))
        raise


def _call_ollama(
    system_prompt: str, user_prompt: str,
    agent_name: str, item_label: str, max_turns: int,
) -> bool:
    import urllib.request

    model = os.environ.get("OLLAMA_MODEL", "granite4.1:8b")
    num_ctx = int(os.environ.get("OLLAMA_NUM_CTX", "32768"))
    max_tokens = int(os.environ.get("OLLAMA_MAX_TOKENS", "8192"))
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    openai_tools = convert_tools_to_openai(TOOLS_SCHEMA)

    m = metrics.RunMetrics(
        agent_name=agent_name,
        provider="ollama",
        model=model,
        model_variant=item_label,
        pipeline_step=os.environ.get("AGENT_PIPELINE_STEP"),
        trigger=os.environ.get("AGENT_TRIGGER", "scheduled"),
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    wrote = False
    try:
        for turn in range(max_turns):
            t_api = time.monotonic()
            payload = {
                "model": model, "messages": messages, "tools": openai_tools,
                "stream": False, "think": False,
                "options": {"num_predict": max_tokens, "num_ctx": num_ctx, "temperature": 0},
            }
            req = urllib.request.Request(
                f"{base_url}/api/chat",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=300) as resp:
                raw = json.load(resp)
            api_latency = time.monotonic() - t_api

            response = OllamaResponse(raw)
            msg = raw.get("message", {})
            tool_calls = msg.get("tool_calls", [])

            if not tool_calls:
                m.record_turn(response, [], api_latency)
                break

            turn_tool_names = []
            messages.append(msg)
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments", {})
                if isinstance(args, str):
                    args = json.loads(args)
                turn_tool_names.append(name)

                if name in TOOL_FN:
                    result = TOOL_FN[name](args)
                    if name in ("ReplaceSection", "Edit") and "Error" not in result:
                        wrote = True
                        print(f"    ✅ {name}({args.get('file_path','')[:50]}, {args.get('section','')})", file=sys.stderr)
                    elif "Error" in result:
                        print(f"    ⚠️  {result[:80]}", file=sys.stderr)
                    messages.append({"role": "tool", "content": result, "tool_name": name})
                else:
                    messages.append({"role": "tool", "content": f"Unknown tool: {name}", "tool_name": name})

            m.record_turn(response, turn_tool_names, api_latency)

        m.finalize(completed=True, stop_reason="stop")
    except Exception as e:
        m.finalize(completed=False, stop_reason="error", error_message=str(e))
        raise

    return wrote


def _call_anthropic(
    system_prompt: str, user_prompt: str,
    agent_name: str, item_label: str, max_turns: int,
) -> bool:
    import anthropic

    if os.environ.get("CLAUDE_CODE_USE_VERTEX"):
        client = anthropic.AnthropicVertex(
            project_id=os.environ["ANTHROPIC_VERTEX_PROJECT_ID"],
            region=os.environ.get("ANTHROPIC_VERTEX_REGION", "us-east5"),
        )
    else:
        client = anthropic.Anthropic()

    model = os.environ.get("DAILY_SYNC_MODEL") \
        or os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL") \
        or "claude-haiku-4-5"
    if os.environ.get("CLAUDE_CODE_USE_VERTEX"):
        model = model.split("[")[0]

    anthropic_tools = [
        {"name": t["name"], "description": t["description"], "input_schema": t["input_schema"]}
        for t in TOOLS_SCHEMA
    ]

    m = metrics.RunMetrics(
        agent_name=agent_name,
        provider="vertex" if os.environ.get("CLAUDE_CODE_USE_VERTEX") else "anthropic",
        model=model,
        model_variant=item_label,
        pipeline_step=os.environ.get("AGENT_PIPELINE_STEP"),
        trigger=os.environ.get("AGENT_TRIGGER", "scheduled"),
    )

    messages = [{"role": "user", "content": user_prompt}]
    wrote = False

    try:
        for turn in range(max_turns):
            t_api = time.monotonic()
            response = client.messages.create(
                model=model, max_tokens=4096,
                system=system_prompt, tools=anthropic_tools, messages=messages,
            )
            api_latency = time.monotonic() - t_api

            if response.stop_reason == "tool_use":
                turn_tool_names = []
                assistant_content = []
                tool_results = []
                for b in response.content:
                    if b.type == "text":
                        assistant_content.append({"type": "text", "text": b.text})
                    elif b.type == "tool_use":
                        assistant_content.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
                        turn_tool_names.append(b.name)
                        if b.name in TOOL_FN:
                            result = TOOL_FN[b.name](b.input)
                            if b.name in ("ReplaceSection", "Edit") and "Error" not in result:
                                wrote = True
                                print(f"    ✅ {b.name}({b.input.get('file_path','')[:50]}, {b.input.get('section','')})", file=sys.stderr)
                            elif "Error" in result:
                                print(f"    ⚠️  {result[:80]}", file=sys.stderr)
                        else:
                            result = f"Unknown tool: {b.name}"
                        tool_results.append({"type": "tool_result", "tool_use_id": b.id, "content": result})

                m.record_turn(response, turn_tool_names, api_latency)
                messages.append({"role": "assistant", "content": assistant_content})
                messages.append({"role": "user", "content": tool_results})
            else:
                m.record_turn(response, [], api_latency)
                break

        m.finalize(completed=True, stop_reason=getattr(response, 'stop_reason', 'stop'))
    except Exception as e:
        m.finalize(completed=False, stop_reason="error", error_message=str(e))
        raise

    return wrote
