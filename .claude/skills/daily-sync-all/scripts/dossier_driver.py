#!/usr/bin/env python3
# /// script
# dependencies = ["anthropic[vertex]>=0.40", "httpx>=0.27"]
# ///
"""Hybrid dossier driver: Python reads the staging JSON and loops over people,
LLM synthesizes one dossier at a time with a fresh, small context.

Usage:
    uv run dossier_driver.py <dossier-json-path>
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import tools as T
from driver_llm import call_llm as _call_llm


def _find_vault_root() -> str:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".obsidian").is_dir():
            return str(parent)
    raise RuntimeError("Could not find vault root")


VAULT_DIR = Path(os.environ.get("VAULT_DIR") or _find_vault_root())

SYSTEM_PROMPT = """You are a dossier synthesizer. You will receive one person's data and their current People page content.

YOUR TASK: Synthesize a ## Dossier section and write it using the ReplaceSection or Edit tool. You MUST call a tool to write — do not just describe the dossier.

CORRECT callout format: `> [!info]` (single bracket). INCORRECT: `> [[!info]` (wiki-link syntax, never use)."""

PERSON_PROMPT = """Synthesize a ## Dossier for **{name}** and write it to their People page.

**File:** {page_path}
**Today:** {today}

## Person Data

### Identity
{identity_text}

### Role (FastRover)
{fastrover_text}

### Slack Messages ({slack_count} messages)
{slack_text}

### Slack Channels
{channels_text}

### Email Threads ({email_count} threads)
{email_text}

### Meetings ({meeting_count} meetings)
{meeting_text}

### JIRA Issues ({jira_count} issues)
{jira_text}

### Daily Note Mentions
{mentions_text}

## Current People Page Content
```
{page_content}
```

## Instructions

Write the dossier with these subsections:

### Role & Organization
- Combine title with Slack channels to describe what they actually do
- Include team, reporting line (wiki-link manager if page exists), location if notable
- List active channels

### Current Work (OMIT if no Slack/email/JIRA/mention evidence)
- 2-5 bullets grouping related items into work stream themes
- Present tense, active voice
- Wiki-link JIRA keys: [[jira/KEY|KEY]]

### Recent Activity
- Slack: N messages across channels
- Email: N threads with subjects
- Meetings: wiki-linked, up to 5 most recent

## Writing

If the page has `%% section:dossier %%` markers, call:
  ReplaceSection(file_path="{page_path}", section="dossier", content="## Dossier\\n\\n> [!info] Auto-generated on {today}\\n\\n### Role & Organization\\n...")

If no markers, use Edit to replace the existing ## Dossier section, or append at end.

You MUST call ReplaceSection or Edit. Do not just output text."""


def format_identity(person: dict) -> str:
    ident = person.get("identity", {})
    if not ident:
        return "(none)"
    return f"Email: {ident.get('email', '?')}, UID: {ident.get('uid', '?')}, Slack: {ident.get('slack_display', '?')}"


def format_fastrover(person: dict) -> str:
    fr = person.get("fastrover", {})
    if not fr:
        return "(none)"
    lines = []
    if fr.get("title"): lines.append(f"Title: {fr['title']}")
    if fr.get("manager_name"): lines.append(f"Manager: {fr['manager_name']} (page exists: {fr.get('manager_page_exists', False)})")
    if fr.get("location"): lines.append(f"Location: {fr['location']}")
    if fr.get("timezone"): lines.append(f"Timezone: {fr['timezone']}")
    return "\n".join(lines) or "(none)"


def format_slack(person: dict) -> str:
    msgs = person.get("slack_messages", [])
    if not msgs:
        return "(none)"
    lines = []
    for m in msgs[:15]:  # cap at 15 to keep context small
        lines.append(f"- #{m.get('channel','?')} ({m.get('date','?')}): {m.get('content','')[:100]}")
    if len(msgs) > 15:
        lines.append(f"  (+{len(msgs)-15} more)")
    return "\n".join(lines)


def format_email(person: dict) -> str:
    threads = person.get("email_threads", [])
    if not threads:
        return "(none)"
    return "\n".join(f"- {t.get('subject','?')} ({t.get('date','?')}): {t.get('snippet','')[:80]}" for t in threads)


def format_meetings(person: dict) -> str:
    meetings = person.get("meetings", [])
    if not meetings:
        return "(none)"
    lines = []
    for m in meetings[:10]:
        lines.append(f"- {m.get('title','?')} ({m.get('date','?')}) — {m.get('path','?')}")
    if len(meetings) > 10:
        lines.append(f"  (+{len(meetings)-10} more)")
    return "\n".join(lines)


def format_jira(person: dict) -> str:
    issues = person.get("jira_issues", [])
    if not issues:
        return "(none)"
    return "\n".join(f"- {i['key']}: {i.get('summary','?')} [{i.get('status','?')}] ({i.get('role','?')})" for i in issues)


def format_mentions(person: dict) -> str:
    mentions = person.get("daily_mentions", [])
    if not mentions:
        return "(none)"
    return "\n".join(f"- {m.get('date','?')}: {m.get('context','')[:100]}" for m in mentions[:10])


def build_prompt(person: dict, page_content: str, today: str) -> str:
    return PERSON_PROMPT.format(
        name=person["name"],
        page_path=person["page_path"],
        today=today,
        identity_text=format_identity(person),
        fastrover_text=format_fastrover(person),
        slack_count=len(person.get("slack_messages", [])),
        slack_text=format_slack(person),
        channels_text=", ".join(person.get("slack_channels", [])) or "(none)",
        email_count=len(person.get("email_threads", [])),
        email_text=format_email(person),
        meeting_count=len(person.get("meetings", [])),
        meeting_text=format_meetings(person),
        jira_count=len(person.get("jira_issues", [])),
        jira_text=format_jira(person),
        mentions_text=format_mentions(person),
        page_content=page_content[:3000],  # cap page content
    )


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <dossier-json-path>", file=sys.stderr)
        sys.exit(1)

    json_path = sys.argv[1]
    with open(json_path) as f:
        data = json.load(f)

    people = data.get("people", [])
    if not people:
        print("[driver] No people in JSON, exiting", file=sys.stderr)
        return

    today = time.strftime("%Y-%m-%d")
    provider = os.environ.get("AGENT_PROVIDER", "anthropic")
    model = os.environ.get("OLLAMA_MODEL", "granite4.1:8b") if provider == "ollama" else "sonnet"
    print(f"[driver] {len(people)} people, provider={provider}, model={model}", file=sys.stderr)

    wall_start = time.monotonic()
    updated = skipped = errors = 0

    for person in people:
        name = person["name"]
        page_path = person.get("page_path", f"People/{name}.md")
        full_path = VAULT_DIR / page_path

        if not full_path.exists():
            print(f"  [SKIP] {name}: {page_path} not found", file=sys.stderr)
            skipped += 1
            continue

        page_content = full_path.read_text()
        prompt = build_prompt(person, page_content, today)
        prompt_chars = len(prompt)

        evidence = sum(len(person.get(k, [])) for k in ["slack_messages", "email_threads", "meetings", "jira_issues", "daily_mentions"])
        print(f"  [{evidence:>3} items] {name} ({prompt_chars} chars)", file=sys.stderr)

        try:
            wrote = _call_llm(SYSTEM_PROMPT, prompt, "dossier-synthesizer", name)
            if wrote:
                updated += 1
            else:
                print(f"    ❌ LLM did not write", file=sys.stderr)
                errors += 1
        except Exception as e:
            print(f"    ❌ Error: {e}", file=sys.stderr)
            errors += 1

    elapsed = time.monotonic() - wall_start
    print(f"\n[driver] Done in {elapsed:.1f}s: {updated} updated, {skipped} skipped, {errors} errors", file=sys.stderr)


if __name__ == "__main__":
    main()
