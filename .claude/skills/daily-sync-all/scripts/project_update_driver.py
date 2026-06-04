#!/usr/bin/env python3
# /// script
# dependencies = ["anthropic[vertex]>=0.40", "httpx>=0.27"]
# ///
"""Hybrid project-updater driver.

Python handles discovery and data gathering (deterministic, fast).
LLM handles judgment: synthesizing Related Items, executing @claude directives.

The LLM is called once per project with pre-gathered data and a focused prompt.

Usage:
    uv run project_update_driver.py [--dry-run]

Env vars:
    VAULT_DIR         — vault root (auto-detected if unset)
    AGENT_PROVIDER    — "anthropic" (default) or "ollama"
    OLLAMA_MODEL      — model name for ollama (default: granite4.1:8b)
    OLLAMA_NUM_CTX    — context window (default: 32768)
    OLLAMA_MAX_TOKENS — max output tokens (default: 8192)
"""

import json
import os
import re
import subprocess
import sqlite3
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
SLACK_DB = Path.home() / ".config" / "pkm-sync" / "slack.db"
DRY_RUN = "--dry-run" in sys.argv


# ============================================================
# Phase 1: Discovery (pure Python)
# ============================================================

def parse_pipeline(filepath: Path, columns: set[str]) -> list[dict]:
    """Extract wiki-link items from pipeline columns."""
    if not filepath.exists():
        print(f"[driver] WARNING: {filepath.name} not found", file=sys.stderr)
        return []
    text = filepath.read_text()
    projects = []
    current_col = None
    for line in text.splitlines():
        if line.startswith("## "):
            current_col = line[3:].strip()
        elif current_col in columns:
            m = re.search(r'\[\[([^\]|]+)(?:\|([^\]]+))?\]\]', line)
            if m:
                projects.append({
                    "name": m.group(1),
                    "display": m.group(2) or m.group(1),
                    "column": current_col,
                    "pipeline": filepath.stem,
                })
    return projects


def resolve_project_path(name: str) -> Path | None:
    """Find the project note file."""
    for prefix in ["Projects/Work", "Projects/Personal"]:
        p = VAULT_DIR / prefix / f"{name}.md"
        if p.exists():
            return p
    for p in VAULT_DIR.glob(f"Projects/**/{name}.md"):
        if "Archived" not in str(p):
            return p
    area = VAULT_DIR / "Areas" / f"{name}.md"
    return area if area.exists() else None


# ============================================================
# Phase 2: Data Gathering (Python, no LLM)
# ============================================================

def extract_match_criteria(project_path: Path) -> dict:
    """Extract JIRA keys and keywords from frontmatter or body."""
    text = project_path.read_text()
    lines = text.splitlines()
    jira_keys = []
    keywords = []

    # Parse frontmatter
    if lines and lines[0].strip() == "---":
        fm_end = next((i for i, l in enumerate(lines[1:], 1) if l.strip() == "---"), None)
        if fm_end:
            fm = "\n".join(lines[1:fm_end])
            # jira_keys
            jk = re.search(r'jira_keys:\s*\[([^\]]*)\]', fm)
            if jk:
                jira_keys = [k.strip().strip("'\"") for k in jk.group(1).split(",") if k.strip()]
            else:
                in_jk = False
                for l in lines[1:fm_end]:
                    if l.strip().startswith("jira_keys:"):
                        in_jk = True; continue
                    if in_jk and l.strip().startswith("- "):
                        jira_keys.append(l.strip()[2:].strip().strip("'\""))
                    elif in_jk and not l.startswith(" "):
                        in_jk = False
            # keywords
            kw = re.search(r'keywords:\s*\[([^\]]*)\]', fm)
            if kw:
                keywords = [k.strip().strip("'\"") for k in kw.group(1).split(",") if k.strip()]
            else:
                in_kw = False
                for l in lines[1:fm_end]:
                    if l.strip().startswith("keywords:"):
                        in_kw = True; continue
                    if in_kw and l.strip().startswith("- "):
                        keywords.append(l.strip()[2:].strip().strip("'\""))
                    elif in_kw and not l.startswith(" "):
                        in_kw = False

    if not jira_keys:
        jira_keys = list(set(re.findall(r'[A-Z]+-\d+', text)))
    if not keywords:
        keywords = [project_path.stem.lower()]

    return {"jira_keys": jira_keys, "keywords": keywords}


def match_jira(keys: list[str], keywords: list[str]) -> list[dict]:
    jira_dir = VAULT_DIR / "jira"
    if not jira_dir.exists():
        return []
    matches = {}
    for key in keys:
        f = jira_dir / f"{key}.md"
        if f.exists():
            matches[key] = _parse_jira_fm(f, key)
    if not matches and keywords:
        for f in jira_dir.glob("*.md"):
            head = "\n".join(f.read_text().splitlines()[:15]).lower()
            if any(kw.lower() in head for kw in keywords):
                key = f.stem
                if key not in matches:
                    matches[key] = _parse_jira_fm(f, key)
    return list(matches.values())


def _parse_jira_fm(f: Path, key: str) -> dict:
    summary = status = ""
    for line in f.read_text().splitlines()[:15]:
        if line.startswith("summary:"):
            summary = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("status:"):
            status = line.split(":", 1)[1].strip().strip('"')
    return {"key": key, "summary": summary, "status": status}


def match_prs(keys: list[str], keywords: list[str]) -> list[dict]:
    prs_dir = VAULT_DIR / "prs"
    if not prs_dir.exists():
        return []
    matches = []
    for f in prs_dir.glob("*.md"):
        head = "\n".join(f.read_text().splitlines()[:20]).lower()
        if any(kw.lower() in head for kw in keywords + keys):
            title = draft = ""
            for line in f.read_text().splitlines()[:20]:
                if line.startswith("title:"):
                    title = line.split(":", 1)[1].strip().strip('"')
                elif line.startswith("draft:"):
                    draft = line.split(":", 1)[1].strip()
            matches.append({"file": f.stem, "title": title, "status": "Draft" if draft.lower() == "true" else "Open"})
    return matches


def match_drive(keywords: list[str]) -> list[dict]:
    drive_dir = VAULT_DIR / "Drive"
    if not drive_dir.exists():
        return []
    matches = []
    for f in drive_dir.glob("*.md"):
        if any(kw.lower() in f.stem.lower() for kw in keywords):
            matches.append({"file": f.stem})
    return matches


def match_meetings(keywords: list[str], days: int = 14) -> list[dict]:
    """Match meeting notes from the last N days by filename keyword."""
    import datetime
    matches = []
    today = datetime.date.today()
    for i in range(days):
        d = today - datetime.timedelta(days=i)
        month_dir = VAULT_DIR / "Meetings" / str(d.year) / f"{d.strftime('%m-%B')}"
        if not month_dir.exists():
            continue
        for f in month_dir.rglob("*.md"):
            if any(kw.lower() in f.stem.lower() for kw in keywords):
                matches.append({"file": str(f.relative_to(VAULT_DIR)), "name": f.stem})
    return matches


def match_slack(keywords: list[str], days: int = 14) -> list[dict]:
    """Query Slack DB for keyword matches."""
    if not SLACK_DB.exists():
        return []
    matches = []
    try:
        conn = sqlite3.connect(str(SLACK_DB))
        for kw in keywords[:3]:  # limit queries
            rows = conn.execute(
                "SELECT channel_name, author, substr(content, 1, 120), created_at "
                "FROM slack_messages WHERE content LIKE ? "
                "AND created_at >= date('now', ?) "
                "ORDER BY created_at DESC LIMIT 5",
                (f"%{kw}%", f"-{days} days")
            ).fetchall()
            for r in rows:
                matches.append({
                    "channel": r[0], "author": r[1],
                    "snippet": r[2], "date": r[3][:10],
                })
        conn.close()
    except Exception as e:
        print(f"[driver] Slack DB error: {e}", file=sys.stderr)
    return matches


def match_gmail(keywords: list[str]) -> list[dict]:
    """Search Gmail via pkm-sync."""
    matches = []
    try:
        for kw in keywords[:2]:
            result = subprocess.run(
                ["pkm-sync", "search", kw, "--limit", "3", "--format", "json"],
                capture_output=True, text=True, timeout=15
            )
            if result.returncode == 0 and result.stdout.strip():
                data = json.loads(result.stdout)
                items = data.get("results", data) if isinstance(data, dict) else data
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            matches.append({
                                "subject": item.get("title", item.get("path", ""))[:80],
                                "snippet": item.get("snippet", item.get("content", ""))[:120],
                                "date": item.get("date", ""),
                            })
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"[driver] pkm-sync error: {e}", file=sys.stderr)
    return matches


def find_directives(project_path: Path) -> list[dict]:
    """Find unprocessed @claude directives."""
    text = project_path.read_text()
    directives = []
    current_section = ""
    for i, line in enumerate(text.splitlines()):
        if line.startswith("## "):
            current_section = line
        if re.match(r'\s*@claude,', line) and not re.match(r'\s*@claude \(done', line) and not re.match(r'\s*@claude \(skipped', line):
            directives.append({
                "line_num": i + 1,
                "text": line.strip(),
                "section": current_section,
            })
    return directives[:5]


def gather_project_data(project: dict, project_path: Path) -> dict:
    """Gather all data for a single project."""
    criteria = extract_match_criteria(project_path)
    note_content = project_path.read_text()

    # Keep note content manageable — first 80 lines
    note_preview = "\n".join(note_content.splitlines()[:80])

    data = {
        "project": project,
        "path": str(project_path.relative_to(VAULT_DIR)),
        "criteria": criteria,
        "note_preview": note_preview,
        "jira": match_jira(criteria["jira_keys"], criteria["keywords"]),
        "prs": match_prs(criteria["jira_keys"], criteria["keywords"]),
        "drive": match_drive(criteria["keywords"]),
        "meetings": match_meetings(criteria["keywords"]),
        "slack": match_slack(criteria["keywords"]),
        "gmail": match_gmail(criteria["keywords"]),
        "directives": find_directives(project_path),
    }
    total = sum(len(data[k]) for k in ["jira", "prs", "drive", "meetings", "slack", "gmail"])
    data["total_matches"] = total
    return data


# ============================================================
# Phase 3: LLM Writing (focused, per-project)
# ============================================================

WRITE_PROMPT = """You are a project-updater agent. I have pre-gathered data for the project below.

YOUR TASK: Write the ## Related Items section using the ReplaceSection tool. You MUST call ReplaceSection — do not just describe what you would write.

## Project: {display}
**File:** {path}
**Pipeline:** {pipeline} — {column}

## Pre-Gathered Data

### JIRA Issues
{jira_text}

### Pull Requests
{prs_text}

### Drive Documents
{drive_text}

### Recent Meetings (14 days)
{meetings_text}

### Slack Messages (14 days)
{slack_text}

### Gmail Threads
{gmail_text}

{directives_text}

## Instructions

1. Call ReplaceSection(file_path="{path}", section="related-items", content="...") with the formatted Related Items section.
2. The content MUST start with "## Related Items" and include an info callout: > [!info] Auto-generated by project-updater on {today}. Do not edit manually.
3. Format: JIRA and PRs as tables with wiki-links (escape pipes in tables: [[jira/KEY\\|KEY]]). Documents, Meetings, Slack, Gmail as bullet lists.
4. Omit any subsection with zero matches.
5. Truncate long text to ~60 chars.
{directive_instructions}
IMPORTANT: You MUST call the ReplaceSection tool. Output nothing else."""


def format_matches(items: list[dict], fmt: str) -> str:
    if not items:
        return "(none)"
    lines = []
    for item in items:
        if fmt == "jira":
            lines.append(f"- {item['key']}: {item['summary'][:80]} [{item['status']}]")
        elif fmt == "pr":
            lines.append(f"- {item['file']}: {item['title'][:80]} [{item['status']}]")
        elif fmt == "drive":
            lines.append(f"- {item['file']}")
        elif fmt == "meeting":
            lines.append(f"- {item['name']} ({item['file']})")
        elif fmt == "slack":
            lines.append(f"- #{item['channel']} @{item['author']}: {item['snippet']} ({item['date']})")
        elif fmt == "gmail":
            lines.append(f"- {item['subject']}: {item['snippet']} ({item['date']})")
    return "\n".join(lines)


def build_llm_prompt(data: dict) -> str:
    today = time.strftime("%Y-%m-%d")
    directives_text = ""
    directive_instructions = ""
    if data["directives"]:
        directives_text = "### @claude Directives (unprocessed)\n"
        for d in data["directives"]:
            directives_text += f"- Line {d['line_num']} in {d['section']}: {d['text']}\n"
        directive_instructions = (
            f"6. Process any @claude directives: execute the instruction using Edit, "
            f"then mark done: @claude (done {today}), <instruction>\n"
        )

    return WRITE_PROMPT.format(
        display=data["project"]["display"],
        path=data["path"],
        pipeline=data["project"]["pipeline"],
        column=data["project"]["column"],
        jira_text=format_matches(data["jira"], "jira"),
        prs_text=format_matches(data["prs"], "pr"),
        drive_text=format_matches(data["drive"], "drive"),
        meetings_text=format_matches(data["meetings"], "meeting"),
        slack_text=format_matches(data["slack"], "slack"),
        gmail_text=format_matches(data["gmail"], "gmail"),
        directives_text=directives_text,
        directive_instructions=directive_instructions,
        today=today,
    )




# ============================================================
# Main
# ============================================================

def main():
    wall_start = time.monotonic()

    work = parse_pipeline(VAULT_DIR / "Work Pipeline.md", {"Ideas", "Early", "Mature"})
    personal = parse_pipeline(VAULT_DIR / "Personal Pipeline.md", {"Ideas", "Active", "On Hold"})
    all_projects = work + personal

    provider = os.environ.get("AGENT_PROVIDER", "anthropic")
    model = os.environ.get("OLLAMA_MODEL", "granite4.1:8b") if provider == "ollama" else "sonnet"
    print(f"[driver] {len(all_projects)} projects, provider={provider}, model={model}", file=sys.stderr)

    updated = skipped = errors = no_matches = 0

    for project in all_projects:
        path = resolve_project_path(project["name"])
        if not path:
            print(f"  [SKIP] {project['display']}: file not found", file=sys.stderr)
            skipped += 1
            continue

        try:
            data = gather_project_data(project, path)

            if data["total_matches"] == 0 and not data["directives"]:
                print(f"  [----] {project['display']}: no matches, no directives", file=sys.stderr)
                no_matches += 1
                continue

            counts = f"{len(data['jira'])}J {len(data['prs'])}P {len(data['drive'])}D {len(data['meetings'])}M {len(data['slack'])}S {len(data['gmail'])}G"
            dirs = f" +{len(data['directives'])} directives" if data["directives"] else ""
            print(f"  [{project['column']:>7}] {project['display']}: {counts}{dirs}", file=sys.stderr)

            if DRY_RUN:
                print(f"    [dry-run] would call LLM", file=sys.stderr)
                continue

            prompt = build_llm_prompt(data)
            system = "You are a project-updater agent. Use the provided tools to update project files. Always call ReplaceSection when asked."
            wrote = _call_llm(system, prompt, "project-updater", project["display"])

            if wrote:
                updated += 1
            else:
                print(f"    ❌ LLM did not write (no tool calls)", file=sys.stderr)
                errors += 1

        except Exception as e:
            print(f"  [ERROR] {project['display']}: {e}", file=sys.stderr)
            errors += 1

    elapsed = time.monotonic() - wall_start
    print(f"\n[driver] Done in {elapsed:.1f}s: {updated} updated, {no_matches} no-matches, {skipped} skipped, {errors} errors", file=sys.stderr)


if __name__ == "__main__":
    main()
