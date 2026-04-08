#!/usr/bin/env python3
"""Auto-create People pages for unresolved meeting attendees using FastRover.

Scans meeting notes for attendees stored as [[email@redhat.com]] wiki-links
that couldn't be resolved to an existing People page. For each such email,
looks up the employee in the FastRover directory and creates People/<Full Name>.md
with structured frontmatter populated from FastRover data.

Run after normalize_attendees.py (pass 1) and before it runs again (pass 2).

Usage:
    python3 create_people_pages.py [--dry-run] <directory_or_file> [<file2> ...]
    python3 create_people_pages.py Meetings/2026/03-March/
    python3 create_people_pages.py --dry-run Meetings/
"""

import gzip
import json
import os
import re
import sys
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).parent))

from sync_calendar import build_people_index

SELF_EMAIL = os.environ.get("PKM_USER_EMAIL", "")
FASTROVER_PATH = Path.home() / ".cache/fastrover/all_users.json.gz"
SLACK_CACHE_PATH = Path.home() / ".config/pkm-sync/slack-user-cache.json"
PEOPLE_DIR = VAULT_ROOT / "People"
TEMPLATE_PATH = VAULT_ROOT / "Templates/Person.md"

# Emails to always skip (calendar resources, groups)
SKIP_DOMAINS = {"resource.calendar.google.com", "group.calendar.google.com"}
EMAIL_RE = re.compile(r'\[\[([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+)\]\]')
# Gemini-generated meeting notes store attendees as [Name](mailto:email) in the body
MAILTO_RE = re.compile(r'\[([^\]]+)\]\(mailto:([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+)\)')


def load_fastrover() -> dict[str, dict]:
    """Load FastRover cache, return {email: record} dict."""
    if not FASTROVER_PATH.exists():
        print(f"WARNING: FastRover cache not found at {FASTROVER_PATH}", file=sys.stderr)
        return {}

    import time
    age_days = (time.time() - FASTROVER_PATH.stat().st_mtime) / 86400
    if age_days > 30:
        print(f"WARNING: FastRover cache is {age_days:.0f} days old — consider refreshing", file=sys.stderr)

    try:
        with gzip.open(FASTROVER_PATH, "rt", encoding="utf-8") as f:
            records = json.load(f)
        result = {}
        for rec in records:
            email = rec.get("rhatPrimaryMail", "").lower()
            if email:
                result[email] = rec
            alias = rec.get("rhatPreferredAlias", "").lower()
            if alias and alias != email:
                result.setdefault(alias, rec)
        return result
    except Exception as e:
        print(f"WARNING: Failed to load FastRover cache: {e}", file=sys.stderr)
        return {}


def load_slack_cache() -> dict[str, str]:
    """Load Slack user cache, return {lowercase_display_name: slack_id} reverse index."""
    if not SLACK_CACHE_PATH.exists():
        print(f"WARNING: Slack cache not found at {SLACK_CACHE_PATH}", file=sys.stderr)
        return {}

    try:
        with open(SLACK_CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
        # cache is {slack_id: display_name} — invert it
        return {name.lower(): slack_id for slack_id, name in cache.items()}
    except Exception as e:
        print(f"WARNING: Failed to load Slack cache: {e}", file=sys.stderr)
        return {}


def parse_hire_date(ldap_date: str) -> str:
    """Convert LDAP timestamp YYYYMMDDHHmmssZ to YYYY-MM-DD."""
    if not ldap_date or len(ldap_date) < 8:
        return ""
    try:
        return f"{ldap_date[0:4]}-{ldap_date[4:6]}-{ldap_date[6:8]}"
    except Exception:
        return ""


def make_page_content(record: dict, slack_id: str) -> str:
    """Generate People page content from a FastRover record."""
    email = record.get("rhatPrimaryMail", "")
    uid = record.get("uid", "")
    title = record.get("rhatJobTitle", "") or record.get("title", "")
    manager = record.get("manager", "")
    location = record.get("rhatLocation", "")
    timezone = record.get("preferredTimeZone", "")
    geo = record.get("rhatGeo", "")
    pronouns = record.get("rhatPronouns", "")
    hire_date = parse_hire_date(record.get("rhatHireDate", ""))

    return f"""---
email: {email}
uid: {uid}
slack_id: {slack_id}
title: {title}
manager: {manager}
location: {location}
timezone: {timezone}
geo: {geo}
pronouns: {pronouns}
hire_date: {hire_date}
aliases: []
tags:
  - type/person
---

```dataview
LIST FROM "Meetings" WHERE contains(attendees, this.file.link) SORT file.cday DESC
```
"""


def collect_unresolved_emails(files: list[Path]) -> dict[str, str]:
    """Scan meeting files for unresolved email attendees.

    Handles two formats:
    - YAML frontmatter attendees: [[email@redhat.com]] (pkm-sync meeting notes)
    - Body [Name](mailto:email) links (Gemini-generated transcript notes)

    Returns {email: display_name} where display_name may be empty string.
    """
    unresolved: dict[str, str] = {}

    def _add(email: str, name: str = "") -> None:
        email = email.lower()
        domain = email.split("@", 1)[1] if "@" in email else ""
        if email != SELF_EMAIL.lower() and domain not in SKIP_DOMAINS:
            if email not in unresolved:
                unresolved[email] = name

    for path in files:
        if "sync-conflict" in path.name:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue

        fm_match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)

        if fm_match and "attendees:" in fm_match.group(1):
            # pkm-sync format: scan frontmatter attendees block for [[email]] links
            in_attendees = False
            for line in fm_match.group(1).split("\n"):
                if re.match(r"^attendees:", line):
                    in_attendees = True
                    continue
                if in_attendees:
                    if line and not line.startswith(" ") and not line.startswith("\t"):
                        in_attendees = False
                        continue
                    m = EMAIL_RE.search(line)
                    if m:
                        _add(m.group(1))
        else:
            # Gemini format: no frontmatter, attendees listed as [Name](mailto:email) in body
            # Only scan the first 20 lines (attendee list is near the top)
            for line in content.splitlines()[:20]:
                for m in MAILTO_RE.finditer(line):
                    _add(m.group(2), m.group(1))

    return unresolved


def collect_files(args: list[str]) -> list[Path]:
    files = []
    for arg in args:
        p = Path(arg)
        if not p.is_absolute():
            p = VAULT_ROOT / p
        if p.is_dir():
            files.extend(sorted(p.rglob("*.md")))
        elif p.is_file():
            files.append(p)
        else:
            print(f"WARNING: {p} not found, skipping", file=sys.stderr)
    return files


def main():
    dry_run = "--dry-run" in sys.argv
    path_args = [a for a in sys.argv[1:] if a != "--dry-run"]

    if not path_args:
        print(f"Usage: {sys.argv[0]} [--dry-run] <directory_or_file> [<file2> ...]")
        sys.exit(1)

    if dry_run:
        print("[DRY RUN] No files will be written.")

    # Load data sources
    fastrover = load_fastrover()
    if not fastrover:
        print("No FastRover data available — nothing to do.")
        return

    slack_index = load_slack_cache()

    # Build current people index to check for existing pages
    people_index = build_people_index(VAULT_ROOT)
    existing_names_lower = {name.lower() for name in people_index.get("by_name", {}).values()}

    # Collect unresolved emails from meeting files
    files = collect_files(path_args)
    print(f"Scanning {len(files)} meeting files for unresolved attendees...")
    unresolved = collect_unresolved_emails(files)  # {email: display_name}
    print(f"Found {len(unresolved)} unresolved email(s)")

    created = []
    not_in_fastrover = []

    for email in sorted(unresolved):
        record = fastrover.get(email)
        if not record:
            not_in_fastrover.append(email)
            continue

        full_name = record.get("cn", "").strip()
        if not full_name:
            print(f"  SKIP {email}: FastRover record has no cn (full name)", file=sys.stderr)
            continue

        # Check if a People page already exists for this name
        if full_name.lower() in existing_names_lower:
            print(f"  SKIP {email}: People page already exists for '{full_name}'")
            continue

        page_path = PEOPLE_DIR / f"{full_name}.md"
        if page_path.exists():
            print(f"  SKIP {email}: {page_path.name} already exists on disk")
            continue

        # Find Slack ID via reverse name lookup
        slack_id = slack_index.get(full_name.lower(), "")

        content = make_page_content(record, slack_id)

        if dry_run:
            print(f"  WOULD CREATE: People/{full_name}.md")
            print(f"    email={email}, title={record.get('rhatJobTitle','')}, slack_id={slack_id or '(not found)'}")
        else:
            PEOPLE_DIR.mkdir(parents=True, exist_ok=True)
            page_path.write_text(content, encoding="utf-8")
            print(f"  CREATED: People/{full_name}.md")
            created.append(full_name)

        # Update in-memory index so we don't try to create the same person twice
        existing_names_lower.add(full_name.lower())

    print(f"\nDone: {len(created)} page(s) created")
    if not_in_fastrover:
        print(f"Not in FastRover ({len(not_in_fastrover)}): {sorted(not_in_fastrover)}")


if __name__ == "__main__":
    main()
