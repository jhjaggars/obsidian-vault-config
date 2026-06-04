#!/usr/bin/env python3
# /// script
# dependencies = []
# ///
"""Build per-person dossier data and output a staging JSON file.

Queries Slack, Gmail, Meetings, JIRA, and daily notes to compile
communication history for each target person, then writes structured
JSON for the dossier-synthesizer LLM agent to consume.

Usage:
    uv run build_dossier.py [vault_dir] [--mode daily|batch] [--person "Name"] [--days N]

Output: prints path to staging JSON file on stdout; progress on stderr.
"""

import argparse
import gzip
import json
import os
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

# --- Constants ---
SLACK_DB = Path.home() / ".config/pkm-sync/slack.db"
ARCHIVE_DB = Path.home() / ".config/pkm-sync/archive.db"
FASTROVER_PATH = Path.home() / ".cache/fastrover/all_users.json.gz"
SLACK_CACHE_PATH = Path.home() / ".config/pkm-sync/slack-user-cache.json"

MY_EMAIL = os.environ.get("PKM_USER_EMAIL", "jjaggars@redhat.com")
MY_NAME = os.environ.get("PKM_USER_NAME", "Jesse Jaggars")

STANDARD_FM_FIELDS = {"email", "uid", "title", "manager"}


# --- Data classes ---

@dataclass
class PersonIdentity:
    name: str               # People page filename stem
    email: str = ""         # from frontmatter
    uid: str = ""           # from frontmatter
    slack_id: str = ""      # from frontmatter
    slack_display: str = "" # from slack-user-cache (may differ from page name)


# --- Vault root discovery ---

def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".obsidian").is_dir():
            return parent
    raise RuntimeError("Could not find vault root (no .obsidian/ dir)")


# --- Frontmatter parsing ---

def parse_frontmatter(content: str) -> dict:
    """Parse YAML frontmatter. Returns {} if none or malformed."""
    if not content.startswith("---\n"):
        return {}
    end = content.find("\n---\n", 4)
    if end == -1:
        return {}
    fm_block = content[4:end]
    result = {}
    for line in fm_block.split("\n"):
        m = re.match(r"^(\w[\w_]*):\s*(.*)", line)
        if m:
            key = m.group(1)
            val = m.group(2).strip().strip('"').strip("'")
            # Only store non-empty, non-list-placeholder values
            if val and val not in ("[]", "{}"):
                result[key] = val
    return result


# --- Data loaders ---

def load_fastrover() -> tuple[dict, dict]:
    """Load FastRover cache. Returns (by_email, by_name_lower)."""
    if not FASTROVER_PATH.exists():
        print(f"WARNING: FastRover cache not found at {FASTROVER_PATH}", file=sys.stderr)
        return {}, {}
    try:
        with gzip.open(FASTROVER_PATH, "rt", encoding="utf-8") as f:
            records = json.load(f)
        by_email: dict = {}
        by_name: dict = {}
        for rec in records:
            email = rec.get("rhatPrimaryMail", "").lower()
            if email:
                by_email[email] = rec
            cn = rec.get("cn", "").strip()
            if cn:
                by_name[cn.lower()] = rec
        return by_email, by_name
    except Exception as e:
        print(f"WARNING: FastRover load failed: {e}", file=sys.stderr)
        return {}, {}


def load_slack_user_cache() -> tuple[dict, dict]:
    """Load Slack user cache.

    Returns:
        slack_by_id: {slack_id: display_name}
        slack_by_display: {display_name_lower: slack_id}
    """
    if not SLACK_CACHE_PATH.exists():
        return {}, {}
    try:
        with open(SLACK_CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
        by_id = dict(cache)
        by_display = {name.lower(): sid for sid, name in cache.items()}
        return by_id, by_display
    except Exception as e:
        print(f"WARNING: Slack cache load failed: {e}", file=sys.stderr)
        return {}, {}


# --- Identity index ---

def build_identity_index(vault_root: Path, slack_by_id: dict) -> dict:
    """Build a multi-key identity index from People/*.md frontmatter.

    Returns dict with keys:
        by_name:         {name_lower: PersonIdentity}
        by_email:        {email_lower: PersonIdentity}
        by_slack_id:     {slack_id: PersonIdentity}
        by_uid:          {uid_lower: PersonIdentity}
        by_slack_display:{display_name_lower: PersonIdentity}
    """
    by_name: dict = {}
    by_email: dict = {}
    by_slack_id: dict = {}
    by_uid: dict = {}
    by_slack_display: dict = {}

    people_dir = vault_root / "People"
    for p in people_dir.glob("*.md"):
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        fm = parse_frontmatter(content)
        identity = PersonIdentity(
            name=p.stem,
            email=fm.get("email", ""),
            uid=fm.get("uid", ""),
            slack_id=fm.get("slack_id", ""),
        )

        # Resolve Slack display name via cache
        if identity.slack_id and identity.slack_id in slack_by_id:
            identity.slack_display = slack_by_id[identity.slack_id]

        by_name[p.stem.lower()] = identity
        if identity.email:
            by_email[identity.email.lower()] = identity
        if identity.uid:
            by_uid[identity.uid.lower()] = identity
        if identity.slack_id:
            by_slack_id[identity.slack_id] = identity
        if identity.slack_display:
            by_slack_display[identity.slack_display.lower()] = identity

    return {
        "by_name": by_name,
        "by_email": by_email,
        "by_slack_id": by_slack_id,
        "by_uid": by_uid,
        "by_slack_display": by_slack_display,
    }


def resolve_person(name_or_partial: str, idx: dict) -> Optional[PersonIdentity]:
    """Resolve a name string to a PersonIdentity. Returns None if ambiguous or not found."""
    name_lower = name_or_partial.lower().strip()

    # Exact match
    if name_lower in idx["by_name"]:
        return idx["by_name"][name_lower]

    # All-words-present match (handles partial names like "Ivan" or "Ivan N")
    parts = name_lower.split()
    matches = [id_ for n, id_ in idx["by_name"].items() if all(p in n for p in parts)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"Ambiguous name '{name_or_partial}': {[m.name for m in matches[:5]]}", file=sys.stderr)
        return None

    return None


# --- FastRover extraction ---

def extract_fastrover_data(identity: PersonIdentity, fastrover_by_email: dict,
                           fastrover_by_name: dict, vault_root: Path) -> dict:
    """Extract role/org data from FastRover for this person."""
    record = None
    if identity.email:
        record = fastrover_by_email.get(identity.email.lower())
    if not record and identity.name:
        record = fastrover_by_name.get(identity.name.lower())
    if not record:
        return {}

    # Resolve manager uid → full name
    manager_raw = record.get("manager", "")
    manager_name = ""
    manager_page_exists = False
    if manager_raw:
        # FastRover stores manager as LDAP DN ("uid=agupta,ou=users,...") or just uid
        uid_match = re.search(r"uid=([^,]+)", manager_raw)
        mgr_uid = uid_match.group(1) if uid_match else manager_raw

        # Find manager in FastRover by uid
        for rec in fastrover_by_email.values():
            if rec.get("uid") == mgr_uid:
                manager_name = rec.get("cn", "")
                break

        if manager_name:
            manager_page_exists = (vault_root / "People" / f"{manager_name}.md").exists()

    return {
        "title": record.get("rhatJobTitle", "") or record.get("title", ""),
        "manager_uid": manager_raw,
        "manager_name": manager_name,
        "manager_page_exists": manager_page_exists,
        "location": record.get("rhatLocation", ""),
        "geo": record.get("rhatGeo", ""),
        "timezone": record.get("preferredTimeZone", ""),
    }


# --- Slack extraction ---

def extract_slack_messages(identity: PersonIdentity, days: int) -> dict:
    """Extract recent Slack messages authored by this person."""
    if not SLACK_DB.exists():
        return {"messages": [], "channels": []}

    # Prefer the Slack display name (from cache) over page name — it's what's stored in the DB
    author_search = identity.slack_display or identity.name
    if not author_search:
        return {"messages": [], "channels": []}

    since = (date.today() - timedelta(days=days)).isoformat()
    messages = []
    raw_channels: list = []

    try:
        with sqlite3.connect(SLACK_DB) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT channel_name, content, created_at
                FROM slack_messages
                WHERE author = ?
                  AND created_at >= ?
                ORDER BY created_at DESC
                LIMIT 40
                """,
                (author_search, since),
            ).fetchall()

            for row in rows:
                messages.append({
                    "channel": row["channel_name"],
                    "content": (row["content"] or "")[:250],
                    "date": (row["created_at"] or "")[:10],
                })
                raw_channels.append(row["channel_name"])

            # If exact match produced nothing, try LIKE (handles display name variants)
            if not messages:
                rows = conn.execute(
                    """
                    SELECT channel_name, content, created_at
                    FROM slack_messages
                    WHERE author LIKE ?
                      AND created_at >= ?
                    ORDER BY created_at DESC
                    LIMIT 40
                    """,
                    (f"%{author_search}%", since),
                ).fetchall()
                for row in rows:
                    messages.append({
                        "channel": row["channel_name"],
                        "content": (row["content"] or "")[:250],
                        "date": (row["created_at"] or "")[:10],
                    })
                    raw_channels.append(row["channel_name"])
    except Exception as e:
        print(f"WARNING: Slack query failed for {identity.name}: {e}", file=sys.stderr)

    # Deduplicate and filter to real channels (lowercase-hyphen names)
    seen: set = set()
    channels: list = []
    for ch in raw_channels:
        if ch not in seen and re.match(r"^[a-z][a-z0-9\-_.]+$", ch):
            channels.append(ch)
            seen.add(ch)

    return {"messages": messages, "channels": channels[:15]}


# --- Gmail extraction ---

def extract_email_threads(identity: PersonIdentity, days: int) -> list:
    """Find email threads involving this person.

    Tries pkm-sync search first (fast, semantic), then falls back to
    the archive DB FTS table.
    """
    if not identity.name:
        return []

    since = date.today() - timedelta(days=days)
    threads: list = []

    # Primary: pkm-sync semantic search (gmail source)
    try:
        result = subprocess.run(
            ["pkm-sync", "search", identity.name, "--limit", "10", "--format", "json"],
            capture_output=True, text=True, timeout=20,
        )
        if result.returncode == 0 and result.stdout.strip():
            try:
                items = json.loads(result.stdout)
                if isinstance(items, list):
                    for item in items:
                        src = item.get("source_type", "")
                        if src not in ("gmail", "email"):
                            continue
                        item_date_str = item.get("date", "") or item.get("created_at", "")
                        if item_date_str:
                            try:
                                if date.fromisoformat(item_date_str[:10]) < since:
                                    continue
                            except ValueError:
                                pass
                        threads.append({
                            "subject": item.get("title", item.get("subject", "")),
                            "snippet": (item.get("content", ""))[:200],
                            "date": item_date_str[:10] if item_date_str else "",
                        })
            except (json.JSONDecodeError, TypeError):
                pass
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: FTS search in archive DB
    if not threads and ARCHIVE_DB.exists():
        try:
            with sqlite3.connect(ARCHIVE_DB) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT m.subject, m.date_sent
                    FROM messages m
                    JOIN messages_fts ON messages_fts.rowid = m.rowid
                    WHERE messages_fts MATCH ?
                      AND date(m.date_sent) >= ?
                    ORDER BY m.date_sent DESC
                    LIMIT 8
                    """,
                    (f'"{identity.name}"', since.isoformat()),
                ).fetchall()
                for row in rows:
                    threads.append({
                        "subject": row["subject"] or "",
                        "snippet": "",
                        "date": (row["date_sent"] or "")[:10],
                    })
        except Exception as e:
            print(f"WARNING: Gmail FTS query failed for {identity.name}: {e}", file=sys.stderr)

    return threads


# --- Meeting notes extraction ---

def extract_meetings(identity: PersonIdentity, vault_root: Path, days: int) -> list:
    """Find recent meetings where this person is listed as an attendee."""
    meetings_dir = vault_root / "Meetings"
    if not meetings_dir.exists():
        return []

    since = date.today() - timedelta(days=days)
    name = identity.name
    # Patterns that indicate this person is an attendee
    search_patterns = [f"[[{name}]]", f"[[{name}|"]
    if identity.email:
        search_patterns.append(f"[[{identity.email}]]")

    results: list = []

    try:
        # Walk newest first (Meetings/YYYY/MM-Month/DD-Day/YYYY-MM-DD-Title.md)
        for md_file in sorted(meetings_dir.rglob("*.md"), key=lambda p: p.name, reverse=True):
            fname = md_file.name
            date_match = re.match(r"^(\d{4}-\d{2}-\d{2})-", fname)
            if date_match:
                try:
                    meeting_date = date.fromisoformat(date_match.group(1))
                    if meeting_date < since:
                        continue
                except ValueError:
                    pass

            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            if not any(pat in content for pat in search_patterns):
                continue

            title = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", md_file.stem).replace("-", " ")
            rel_path = str(md_file.relative_to(vault_root))

            results.append({
                "title": title,
                "path": rel_path,
                "date": date_match.group(1) if date_match else "",
                "filename": md_file.stem,
            })

            if len(results) >= 10:
                break
    except Exception as e:
        print(f"WARNING: Meeting scan failed for {identity.name}: {e}", file=sys.stderr)

    return results


# --- JIRA extraction ---

def extract_jira_issues(identity: PersonIdentity, vault_root: Path) -> list:
    """Find JIRA issues where this person is assignee or reporter."""
    jira_dir = vault_root / "jira"
    if not jira_dir.exists():
        return []

    name_lower = identity.name.lower()
    issues: list = []

    try:
        for md_file in jira_dir.glob("*.md"):
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            fm = parse_frontmatter(content)
            role = None
            if name_lower in fm.get("assignee", "").lower():
                role = "assignee"
            elif name_lower in fm.get("reporter", "").lower():
                role = "reporter"
            if role:
                issues.append({
                    "key": fm.get("issue_key", md_file.stem),
                    "summary": fm.get("summary", ""),
                    "status": fm.get("status", ""),
                    "role": role,
                })
    except Exception as e:
        print(f"WARNING: JIRA scan failed for {identity.name}: {e}", file=sys.stderr)

    return issues


# --- Daily note mentions ---

def extract_daily_mentions(identity: PersonIdentity, vault_root: Path, days: int) -> list:
    """Find recent daily note lines that mention this person."""
    daily_dir = vault_root / "daily"
    if not daily_dir.exists():
        return []

    since = date.today() - timedelta(days=days)
    name = identity.name
    search_patterns = [f"[[{name}]]", f"[[{name}|"]
    mentions: list = []

    try:
        for md_file in sorted(daily_dir.rglob("*.md"), key=lambda p: p.name, reverse=True):
            fname = md_file.stem
            date_match = re.match(r"^(\d{4}-\d{2}-\d{2})-", fname)
            if date_match:
                try:
                    if date.fromisoformat(date_match.group(1)) < since:
                        continue
                except ValueError:
                    pass

            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            note_date = date_match.group(1) if date_match else fname[:10]
            for line in content.split("\n"):
                if any(pat in line for pat in search_patterns):
                    context = line.strip()
                    if context:
                        mentions.append({"date": note_date, "context": context[:250]})
                if len(mentions) >= 20:
                    break
            if len(mentions) >= 20:
                break
    except Exception as e:
        print(f"WARNING: Daily note scan failed for {identity.name}: {e}", file=sys.stderr)

    return mentions


# --- Target discovery ---

def discover_targets_daily(vault_root: Path, idx: dict) -> list:
    """Find today's meeting attendees and Slack DM partners."""
    today_str = date.today().isoformat()
    targets: dict = {}

    # 1. Today's meeting notes (files starting with today's date under Meetings/)
    meetings_dir = vault_root / "Meetings"
    if meetings_dir.exists():
        for md_file in meetings_dir.rglob("*.md"):
            if not md_file.name.startswith(today_str):
                continue
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            # Extract wiki-links from the full content (attendees section)
            for m in re.finditer(r"\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]", content):
                linked = m.group(1).strip()
                if "@" in linked:
                    identity = idx["by_email"].get(linked.lower())
                else:
                    identity = idx["by_name"].get(linked.lower())
                if identity and identity.name.lower() != MY_NAME.lower():
                    targets[identity.name] = identity

    # 2. Today's Slack DM channels
    if SLACK_DB.exists():
        try:
            with sqlite3.connect(SLACK_DB) as conn:
                rows = conn.execute(
                    """
                    SELECT DISTINCT channel_name FROM slack_messages
                    WHERE date(created_at) = ? AND channel_name != ?
                    """,
                    (today_str, MY_NAME),
                ).fetchall()
            for row in rows:
                ch = row[0]
                # DM channels look like person names: contain uppercase and spaces
                if re.search(r"[A-Z]", ch) and " " in ch:
                    identity = (idx["by_name"].get(ch.lower()) or
                                idx["by_slack_display"].get(ch.lower()))
                    if identity and identity.name.lower() != MY_NAME.lower():
                        targets[identity.name] = identity
        except Exception as e:
            print(f"WARNING: Slack DM discovery failed: {e}", file=sys.stderr)

    return list(targets.values())


def discover_targets_batch(vault_root: Path, idx: dict, days: int) -> list:
    """Find all people with any recent communication activity."""
    since = (date.today() - timedelta(days=days)).isoformat()
    targets: dict = {}

    # 1. Slack: all distinct message authors in the period
    if SLACK_DB.exists():
        try:
            with sqlite3.connect(SLACK_DB) as conn:
                rows = conn.execute(
                    """
                    SELECT DISTINCT author FROM slack_messages
                    WHERE created_at >= ? AND author != ?
                    """,
                    (since, MY_NAME),
                ).fetchall()
            for row in rows:
                author = row[0]
                identity = (idx["by_slack_display"].get(author.lower()) or
                            idx["by_name"].get(author.lower()))
                if identity:
                    targets[identity.name] = identity
        except Exception as e:
            print(f"WARNING: Slack batch discovery failed: {e}", file=sys.stderr)

    # 2. Meeting attendees in the period
    meetings_dir = vault_root / "Meetings"
    if meetings_dir.exists():
        since_date = date.today() - timedelta(days=days)
        for md_file in meetings_dir.rglob("*.md"):
            fname = md_file.name
            date_match = re.match(r"^(\d{4}-\d{2}-\d{2})-", fname)
            if date_match:
                try:
                    if date.fromisoformat(date_match.group(1)) < since_date:
                        continue
                except ValueError:
                    pass
            try:
                content = md_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for m in re.finditer(r"\[\[([^\]|]+?)(?:\|[^\]]+)?\]\]", content):
                linked = m.group(1).strip()
                if "@" in linked:
                    identity = idx["by_email"].get(linked.lower())
                else:
                    identity = idx["by_name"].get(linked.lower())
                if identity and identity.name.lower() != MY_NAME.lower():
                    targets[identity.name] = identity

    return list(targets.values())


# --- Main ---

def main() -> None:
    parser = argparse.ArgumentParser(description="Build people dossier staging JSON")
    parser.add_argument("vault_dir", nargs="?", default=None)
    parser.add_argument("--mode", choices=["daily", "batch"], default="daily")
    parser.add_argument("--person", help="Build dossier for a single person by name")
    parser.add_argument("--days", type=int, default=None, help="Look-back window in days")
    args = parser.parse_args()

    if args.vault_dir:
        vault_root = Path(args.vault_dir)
    else:
        vault_root = _find_vault_root()

    if not (vault_root / "People").exists():
        print(f"ERROR: People directory not found in {vault_root}", file=sys.stderr)
        sys.exit(1)

    # Determine look-back window
    if args.days is not None:
        days = args.days
    elif args.person:
        days = 30
    elif args.mode == "batch":
        days = 30
    else:
        days = 14

    print("Loading data sources...", file=sys.stderr)
    fastrover_by_email, fastrover_by_name = load_fastrover()
    slack_by_id, _ = load_slack_user_cache()
    idx = build_identity_index(vault_root, slack_by_id)
    print(f"Indexed {len(idx['by_name'])} People pages", file=sys.stderr)

    # Discover targets
    if args.person:
        identity = resolve_person(args.person, idx)
        if not identity:
            print(f"ERROR: Could not find People page for '{args.person}'", file=sys.stderr)
            sys.exit(1)
        targets = [identity]
        mode = "single"
    elif args.mode == "batch":
        targets = discover_targets_batch(vault_root, idx, days)
        mode = "batch"
        print(f"Found {len(targets)} people with activity in last {days} days", file=sys.stderr)
    else:
        targets = discover_targets_daily(vault_root, idx)
        mode = "daily"
        print(f"Found {len(targets)} people for today's dossier updates", file=sys.stderr)

    # Build dossier data for each target
    people_data: list = []
    for identity in targets:
        print(f"  Extracting data for {identity.name}...", file=sys.stderr)

        slack_data = extract_slack_messages(identity, days)
        person_data: dict = {
            "name": identity.name,
            "page_path": f"People/{identity.name}.md",
            "identity": {
                "email": identity.email,
                "uid": identity.uid,
                "slack_id": identity.slack_id,
                "slack_display": identity.slack_display,
            },
            "fastrover": extract_fastrover_data(
                identity, fastrover_by_email, fastrover_by_name, vault_root
            ),
            "slack_messages": slack_data["messages"],
            "slack_channels": slack_data["channels"],
            "email_threads": extract_email_threads(identity, days),
            "meetings": extract_meetings(identity, vault_root, days),
            "jira_issues": extract_jira_issues(identity, vault_root),
            "daily_mentions": extract_daily_mentions(identity, vault_root, days),
        }
        people_data.append(person_data)

    # Write JSON staging file
    staging_dir = vault_root / ".claude/skills/people-dossier/staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    output_path = staging_dir / f"dossier-{mode}-{date.today().isoformat()}.json"

    payload = {
        "generated_at": datetime.now().isoformat(),
        "mode": mode,
        "days_lookback": days,
        "people": people_data,
    }
    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    print(
        f"Wrote dossier data for {len(people_data)} people to {output_path}",
        file=sys.stderr,
    )
    # Print path to stdout for pipeline capture
    print(output_path)


if __name__ == "__main__":
    main()
