#!/usr/bin/env python3
"""
Parse `claude -p --output-format stream-json` and print a human-readable
performance timeline with per-tool-call durations.

Usage:
    bash test_step6.sh 2>&1 | python3 parse_stream.py
    bash test_step6.sh 2>&1 | python3 parse_stream.py --slow 3.0
"""

import json
import sys
import time

# Flag slow tool calls (seconds). Override with --slow N.
SLOW_THRESHOLD = float(sys.argv[sys.argv.index("--slow") + 1]) if "--slow" in sys.argv else 5.0

wall_start = time.monotonic()
pending_tool_name = None
pending_tool_start = None


def elapsed(t=None):
    return (t if t is not None else time.monotonic()) - wall_start


def fmt_t(seconds):
    return f"+{seconds:.1f}s"


def summarize_input(tool_name, inp):
    if tool_name == "Bash":
        cmd = inp.get("command", "")
        return f"$ {cmd[:100]}"
    if tool_name in ("Read", "Write"):
        return inp.get("file_path", "")[-80:]
    if tool_name == "Edit":
        path = inp.get("file_path", "")[-60:]
        old = inp.get("old_string", "")[:30].replace("\n", "↵")
        return f"{path}  [{old}…]"
    if tool_name == "Glob":
        return inp.get("pattern", "")
    if tool_name == "Grep":
        pat = inp.get("pattern", "")
        path = inp.get("path", "")
        return f"{pat!r} in {path}" if path else repr(pat)
    return str(inp)[:80]


def summarize_result(content):
    if isinstance(content, list):
        content = " ".join(
            c.get("text", "") for c in content if c.get("type") == "text"
        )
    text = str(content).strip().replace("\n", " ")
    return text[:120] + ("…" if len(text) > 120 else "")


for raw_line in sys.stdin:
    now = time.monotonic()
    line = raw_line.strip()
    if not line:
        continue

    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        # Non-JSON stderr lines (e.g. from claude startup)
        print(f"[{fmt_t(elapsed(now))}] {line[:120]}", flush=True)
        continue

    etype = event.get("type")

    if etype == "system":
        model = event.get("model", "?")
        print(f"[{fmt_t(elapsed(now))}] ⚙  model={model}", flush=True)

    elif etype == "assistant":
        msg = event.get("message", {})
        for block in msg.get("content", []):
            btype = block.get("type")
            if btype == "text":
                text = block.get("text", "").strip()
                if text:
                    first = text.split("\n")[0][:120]
                    print(f"[{fmt_t(elapsed(now))}] 💬 {first}", flush=True)
            elif btype == "tool_use":
                tool = block.get("name", "?")
                inp = block.get("input", {})
                desc = summarize_input(tool, inp)
                pending_tool_name = tool
                pending_tool_start = now
                print(f"[{fmt_t(elapsed(now))}] 🔧 {tool}({desc})", flush=True)

    elif etype == "user":
        msg = event.get("message", {})
        for block in msg.get("content", []):
            if block.get("type") == "tool_result":
                duration = (now - pending_tool_start) if pending_tool_start else 0
                slow_flag = " ⚠ SLOW" if duration >= SLOW_THRESHOLD else ""
                preview = summarize_result(block.get("content", ""))
                print(
                    f"[{fmt_t(elapsed(now))}]   └─ {duration:.1f}s{slow_flag}: {preview}",
                    flush=True,
                )
                pending_tool_name = None
                pending_tool_start = None

    elif etype == "result":
        duration_ms = event.get("duration_ms", 0)
        cost = event.get("cost_usd", 0)
        turns = event.get("num_turns", "?")
        subtype = event.get("subtype", "?")
        status = "✅" if subtype == "success" else "❌"
        print(
            f"\n[{fmt_t(elapsed(now))}] {status} {subtype} — "
            f"{duration_ms / 1000:.1f}s total, {turns} turns, ${cost:.4f}",
            flush=True,
        )
        if subtype != "success":
            result_text = event.get("result", "")
            if result_text:
                print(f"           {result_text[:200]}", flush=True)
