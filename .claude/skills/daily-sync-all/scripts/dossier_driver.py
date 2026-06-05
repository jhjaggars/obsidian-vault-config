#!/usr/bin/env python3
# /// script
# dependencies = ["anthropic[vertex]>=0.40", "httpx>=0.27"]
# ///
"""Hybrid dossier driver: Python reads the staging JSON and processes people
in parallel — each person gets an independent LLM call writing to their own
People page (no shared file writes).

Usage:
    uv run dossier_driver.py <dossier-json-path> [--concurrency N]

Concurrency defaults to DOSSIER_CONCURRENCY env var (default: 4).
"""

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import tools as T
from driver_llm import call_llm as _call_llm, call_llm_batch as _call_llm_batch


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


def _process_person(person: dict, today: str) -> tuple[str, str]:
    """Process a single person's dossier (legacy mode). Returns (name, status)."""
    name = person["name"]
    page_path = person.get("page_path", f"People/{name}.md")
    full_path = VAULT_DIR / page_path

    if not full_path.exists():
        print(f"  [SKIP] {name}: {page_path} not found", file=sys.stderr, flush=True)
        return name, "skipped"

    page_content = full_path.read_text()
    prompt = build_prompt(person, page_content, today)
    prompt_chars = len(prompt)

    evidence = sum(len(person.get(k, [])) for k in ["slack_messages", "email_threads", "meetings", "jira_issues", "daily_mentions"])
    print(f"  [{evidence:>3} items] {name} ({prompt_chars} chars)", file=sys.stderr, flush=True)

    try:
        wrote = _call_llm(SYSTEM_PROMPT, prompt, "dossier-synthesizer", name)
        if wrote:
            return name, "updated"
        else:
            print(f"    ❌ LLM did not write for {name}", file=sys.stderr, flush=True)
            return name, "error"
    except Exception as e:
        print(f"    ❌ Error for {name}: {e}", file=sys.stderr, flush=True)
        return name, "error"


# ============================================================
# Batch / Mega-Prompt Mode
# ============================================================

BATCH_SYSTEM = """You are a dossier synthesizer. You will receive data for multiple people.
For EACH person, write a ## Dossier section.

Delimit each person's output with markers:
%%% PERSON: <Person Name> %%%
<dossier content>
%%% /PERSON: <Person Name> %%%

Each dossier MUST start with:
## Dossier

> [!info] Auto-generated on {today}

Include these subsections:
### Role & Organization
- Title, team, manager (wiki-link if page exists), location, active Slack channels

### Current Work (OMIT if no Slack/email/JIRA/mention evidence)
- 2-5 bullets grouping related items into work stream themes
- Present tense, active voice
- Wiki-link JIRA keys: [[jira/KEY|KEY]]

### Recent Activity
- Slack: N messages across channels
- Email: N threads
- Meetings: wiki-linked, up to 5 most recent

Be concise — no commentary, just the dossier sections."""


def build_batch_prompt(people_batch: list[dict], page_contents: dict[str, str], today: str) -> str:
    """Build a single prompt for a batch of people."""
    parts = []
    for person in people_batch:
        name = person["name"]
        page_path = person.get("page_path", f"People/{name}.md")
        page_content = page_contents.get(name, "")

        section = f"""---
## Person: {name}
**File:** {page_path}

### Identity
{format_identity(person)}

### Role (FastRover)
{format_fastrover(person)}

### Slack Messages ({len(person.get('slack_messages', []))} messages)
{format_slack(person)}

### Slack Channels
{', '.join(person.get('slack_channels', [])) or '(none)'}

### Email Threads ({len(person.get('email_threads', []))} threads)
{format_email(person)}

### Meetings ({len(person.get('meetings', []))} meetings)
{format_meetings(person)}

### JIRA Issues ({len(person.get('jira_issues', []))} issues)
{format_jira(person)}

### Daily Note Mentions
{format_mentions(person)}

### Current Page Content (first 2000 chars)
{page_content[:2000]}"""
        parts.append(section)

    header = f"Write dossier sections for the following {len(people_batch)} people.\nToday's date: {today}\n"
    return header + "\n\n".join(parts)


import re as _re


def parse_batch_response(response: str) -> dict[str, str]:
    """Parse %%% PERSON: Name %%% delimited sections from the batch response."""
    sections = {}
    pattern = _re.compile(
        r'%%%\s*PERSON:\s*(.+?)\s*%%%\s*\n(.*?)%%%\s*/PERSON:\s*.+?\s*%%%',
        _re.DOTALL,
    )
    for match in pattern.finditer(response):
        name = match.group(1).strip()
        content = match.group(2).strip()
        sections[name] = content
    return sections


def _write_dossier(name: str, page_path: str, content: str) -> str:
    """Write dossier content to a People page. Tries section markers first, then edit, then append."""
    full_path = VAULT_DIR / page_path
    if not full_path.exists():
        return f"Error: {page_path} not found"

    # Try ReplaceSection first
    result = T.replace_section(str(full_path), "dossier", content)
    if "Error" not in result:
        return result

    # Fallback: try to replace existing ## Dossier section
    text = full_path.read_text()
    dossier_match = _re.search(r'(## Dossier\b.*?)(?=\n## [^#]|\Z)', text, _re.DOTALL)
    if dossier_match:
        result = T.edit(str(full_path), dossier_match.group(0), content)
        if "Error" not in result:
            return result

    # Final fallback: append
    with open(full_path, "a") as f:
        f.write("\n\n" + content + "\n")
    return f"Appended dossier to {page_path}"


def _process_batch(people_batch: list[dict], page_contents: dict[str, str], today: str) -> list[tuple[str, str]]:
    """Process a batch of people via mega-prompt. Returns list of (name, status)."""
    prompt = build_batch_prompt(people_batch, page_contents, today)
    names = [p["name"] for p in people_batch]
    label = f"batch-{len(people_batch)}-{'_'.join(n.split()[0] for n in names[:3])}"

    try:
        response = _call_llm_batch(
            BATCH_SYSTEM.format(today=today),
            prompt,
            "dossier-synthesizer",
            label,
        )
    except Exception as e:
        print(f"    ❌ Batch LLM error: {e}", file=sys.stderr, flush=True)
        return [(n, "error") for n in names]

    sections = parse_batch_response(response)
    results = []
    for person in people_batch:
        name = person["name"]
        page_path = person.get("page_path", f"People/{name}.md")
        if name in sections:
            result = _write_dossier(name, page_path, sections[name])
            if "Error" in result:
                print(f"    ⚠️  {result[:80]}", file=sys.stderr, flush=True)
                results.append((name, "error"))
            else:
                print(f"    ✅ {result}", file=sys.stderr, flush=True)
                results.append((name, "updated"))
        else:
            print(f"    ⚠️  No section found in response for {name}", file=sys.stderr, flush=True)
            results.append((name, "error"))

    return results


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <dossier-json-path> [--concurrency N] [--batch-size N] [--legacy]", file=sys.stderr)
        sys.exit(1)

    json_path = sys.argv[1]
    concurrency = int(os.environ.get("DOSSIER_CONCURRENCY", "4"))
    batch_size = int(os.environ.get("DOSSIER_BATCH_SIZE", "4"))
    legacy = "--legacy" in sys.argv

    if "--concurrency" in sys.argv:
        idx = sys.argv.index("--concurrency")
        if idx + 1 < len(sys.argv):
            concurrency = int(sys.argv[idx + 1])
    if "--batch-size" in sys.argv:
        idx = sys.argv.index("--batch-size")
        if idx + 1 < len(sys.argv):
            batch_size = int(sys.argv[idx + 1])

    with open(json_path) as f:
        data = json.load(f)

    people = data.get("people", [])
    if not people:
        print("[driver] No people in JSON, exiting", file=sys.stderr)
        return

    today = time.strftime("%Y-%m-%d")
    provider = os.environ.get("AGENT_PROVIDER", "anthropic")
    model = os.environ.get("DAILY_SYNC_MODEL") or os.environ.get("ANTHROPIC_DEFAULT_HAIKU_MODEL") or "claude-haiku-4-5"
    mode = "legacy" if legacy else f"batch (size={batch_size})"
    print(f"[driver] {len(people)} people, provider={provider}, model={model}, mode={mode}, concurrency={concurrency}", file=sys.stderr)

    wall_start = time.monotonic()
    updated = skipped = errors = 0

    if legacy:
        # Legacy mode: per-person LLM calls with tool use
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {
                pool.submit(_process_person, person, today): person["name"]
                for person in people
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    _, status = future.result()
                    if status == "updated":
                        updated += 1
                    elif status == "skipped":
                        skipped += 1
                    else:
                        errors += 1
                except Exception as e:
                    print(f"    ❌ Unexpected error for {name}: {e}", file=sys.stderr, flush=True)
                    errors += 1
    else:
        # Batch mode: mega-prompts, no tool calls
        # Pre-read all People page contents
        page_contents = {}
        valid_people = []
        for person in people:
            name = person["name"]
            page_path = person.get("page_path", f"People/{name}.md")
            full_path = VAULT_DIR / page_path
            if not full_path.exists():
                print(f"  [SKIP] {name}: {page_path} not found", file=sys.stderr, flush=True)
                skipped += 1
                continue
            page_contents[name] = full_path.read_text()
            evidence = sum(len(person.get(k, [])) for k in ["slack_messages", "email_threads", "meetings", "jira_issues", "daily_mentions"])
            print(f"  [{evidence:>3} items] {name}", file=sys.stderr, flush=True)
            valid_people.append(person)

        # Group into batches
        batches = [valid_people[i:i + batch_size] for i in range(0, len(valid_people), batch_size)]
        print(f"[driver] {len(batches)} batches of up to {batch_size} people", file=sys.stderr)

        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {
                pool.submit(_process_batch, batch, page_contents, today): idx
                for idx, batch in enumerate(batches)
            }
            for future in as_completed(futures):
                batch_idx = futures[future]
                try:
                    results = future.result()
                    for name, status in results:
                        if status == "updated":
                            updated += 1
                        elif status == "skipped":
                            skipped += 1
                        else:
                            errors += 1
                except Exception as e:
                    print(f"    ❌ Batch {batch_idx} error: {e}", file=sys.stderr, flush=True)
                    errors += len(batches[batch_idx])

    elapsed = time.monotonic() - wall_start
    print(f"\n[driver] Done in {elapsed:.1f}s: {updated} updated, {skipped} skipped, {errors} errors", file=sys.stderr)


if __name__ == "__main__":
    main()
