#!/usr/bin/env python3
# /// script
# dependencies = []
# ///
"""Migrate legacy People pages to add standard frontmatter from FastRover.

Scans People/*.md for pages missing the standard frontmatter fields (email, uid,
title, manager). For each such page, looks up the person in FastRover by full
name (cn field), then prepends standard frontmatter while preserving all
existing body content.

Usage:
    uv run migrate_legacy_people.py [--dry-run] [vault_dir]
    python3 migrate_legacy_people.py --dry-run /path/to/vault
"""

import gzip
import json
import re
import sys
from pathlib import Path

FASTROVER_PATH = Path.home() / ".cache/fastrover/all_users.json.gz"
SLACK_CACHE_PATH = Path.home() / ".config/pkm-sync/slack-user-cache.json"

STANDARD_FM_FIELDS = {"email", "uid", "title", "manager"}

DATAVIEW_QUERY = """```dataview
LIST FROM "Meetings" WHERE contains(attendees, this.file.link) SORT file.cday DESC
```"""


def _find_vault_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".obsidian").is_dir():
            return parent
    raise RuntimeError("Could not find vault root (no .obsidian/ dir)")


def has_standard_frontmatter(content: str) -> bool:
    """Return True if file already has all required standard frontmatter fields."""
    if not content.startswith("---\n"):
        return False
    end = content.find("\n---\n", 4)
    if end == -1:
        return False
    fm_block = content[4:end]
    keys = set(re.findall(r"^(\w[\w_]*):", fm_block, re.MULTILINE))
    return STANDARD_FM_FIELDS.issubset(keys)


def extract_legacy_frontmatter(content: str) -> tuple[dict, str]:
    """Extract any existing frontmatter key/values and the body after it.

    Returns (fm_dict, body_text).
    If no frontmatter delimiters found, returns ({}, full_content).
    """
    if not content.startswith("---\n"):
        return {}, content
    end = content.find("\n---\n", 4)
    if end == -1:
        return {}, content
    fm_block = content[4:end]
    body = content[end + 5:]  # skip the closing \n---\n

    fm_dict = {}
    for line in fm_block.split("\n"):
        m = re.match(r"^(\w[\w_]*):\s*(.*)", line)
        if m:
            fm_dict[m.group(1).strip()] = m.group(2).strip().strip('"').strip("'")
    return fm_dict, body


def has_dataview_query(content: str) -> bool:
    return "contains(attendees, this.file.link)" in content


def load_fastrover() -> tuple[dict, dict]:
    """Load FastRover cache.

    Returns:
        (by_email, by_name_lower): both keyed for case-insensitive lookup
    """
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
        print(f"WARNING: Failed to load FastRover: {e}", file=sys.stderr)
        return {}, {}


def load_slack_cache() -> dict:
    """Load Slack user cache, return {display_name_lower: slack_id}."""
    if not SLACK_CACHE_PATH.exists():
        return {}
    try:
        with open(SLACK_CACHE_PATH, encoding="utf-8") as f:
            cache = json.load(f)
        return {name.lower(): sid for sid, name in cache.items()}
    except Exception as e:
        print(f"WARNING: Failed to load Slack cache: {e}", file=sys.stderr)
        return {}


def parse_hire_date(ldap_date: str) -> str:
    """Convert LDAP timestamp YYYYMMDDHHmmssZ → YYYY-MM-DD."""
    if not ldap_date or len(ldap_date) < 8:
        return ""
    try:
        return f"{ldap_date[0:4]}-{ldap_date[4:6]}-{ldap_date[6:8]}"
    except Exception:
        return ""


def make_frontmatter(record: dict, slack_id: str, aliases: list) -> str:
    email = record.get("rhatPrimaryMail", "")
    uid = record.get("uid", "")
    title = record.get("rhatJobTitle", "") or record.get("title", "")
    manager = record.get("manager", "")
    location = record.get("rhatLocation", "")
    timezone = record.get("preferredTimeZone", "")
    geo = record.get("rhatGeo", "")
    pronouns = record.get("rhatPronouns", "")
    hire_date = parse_hire_date(record.get("rhatHireDate", ""))

    if aliases:
        aliases_str = "\n" + "\n".join(f"  - {a}" for a in aliases)
    else:
        aliases_str = " []"

    return (
        f"---\n"
        f"email: {email}\n"
        f"uid: {uid}\n"
        f"slack_id: {slack_id}\n"
        f"title: {title}\n"
        f"manager: {manager}\n"
        f"location: {location}\n"
        f"timezone: {timezone}\n"
        f"geo: {geo}\n"
        f"pronouns: {pronouns}\n"
        f"hire_date: {hire_date}\n"
        f"aliases:{aliases_str}\n"
        f"tags:\n"
        f"  - type/person\n"
        f"---"
    )


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if args:
        vault_root = Path(args[0])
    else:
        vault_root = _find_vault_root()

    people_dir = vault_root / "People"
    if not people_dir.exists():
        print(f"ERROR: People directory not found at {people_dir}", file=sys.stderr)
        sys.exit(1)

    if dry_run:
        print("[DRY RUN] No files will be written.\n")

    _, fastrover_by_name = load_fastrover()
    if not fastrover_by_name:
        print("No FastRover data available — cannot migrate.")
        return

    slack_reverse = load_slack_cache()

    pages = sorted(people_dir.glob("*.md"))
    needs_migration = []
    for p in pages:
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"WARNING: could not read {p.name}: {e}", file=sys.stderr)
            continue
        if not has_standard_frontmatter(content):
            needs_migration.append(p)

    print(f"Found {len(needs_migration)} page(s) needing migration (of {len(pages)} total)\n")

    migrated = []
    skipped = []

    for p in needs_migration:
        content = p.read_text(encoding="utf-8", errors="replace")
        stem = p.stem  # e.g. "Karanbir Singh"

        # Extract any existing legacy frontmatter and body
        legacy_fm, body = extract_legacy_frontmatter(content)

        # Look up in FastRover by exact name
        record = fastrover_by_name.get(stem.lower())

        if not record:
            # Single-name pages (e.g. "Ciaran"): try first-name prefix match
            parts = stem.split()
            if len(parts) == 1:
                first_lower = parts[0].lower()
                candidates = [
                    r for r in fastrover_by_name.values()
                    if r.get("cn", "").lower().startswith(first_lower + " ")
                ]
                if len(candidates) == 1:
                    record = candidates[0]
                    print(f"  NOTE {stem}: resolved to '{record.get('cn')}' via first-name match")
                elif len(candidates) > 1:
                    print(f"  SKIP {stem}: ambiguous single name — {len(candidates)} FastRover candidates")
                    skipped.append(stem)
                    continue

        if not record:
            print(f"  SKIP {stem}: not found in FastRover")
            skipped.append(stem)
            continue

        full_name = record.get("cn", stem).strip()

        # Collect aliases from the legacy frontmatter
        aliases: list[str] = []
        for key in ("alias", "aliases"):
            val = legacy_fm.get(key, "").strip()
            if val and val not in ("[]", ""):
                # Could be a bare value like "KB" or a list item "- KB"
                for item in re.findall(r"(?:^|\-\s*)([^\[\]\n]+)", val):
                    item = item.strip()
                    if item:
                        aliases.append(item)

        slack_id = slack_reverse.get(full_name.lower(), "")

        new_fm = make_frontmatter(record, slack_id, aliases)

        # Strip any existing dataview block from body, then append fresh one
        body_clean = re.sub(r"```dataview[^`]*```\s*", "", body, flags=re.DOTALL).strip()

        # Assemble new file content
        parts_out = [new_fm, "", DATAVIEW_QUERY]
        if body_clean:
            parts_out += ["", body_clean]
        parts_out.append("")  # trailing newline
        new_content = "\n".join(parts_out)

        if dry_run:
            print(f"  WOULD MIGRATE: {p.name}")
            print(f"    FastRover: {full_name} — {record.get('rhatJobTitle', '(no title)')}")
            print(f"    Slack ID:  {slack_id or '(not found)'}")
            if aliases:
                print(f"    Aliases:   {aliases}")
            if body_clean:
                preview = body_clean[:80].replace("\n", " ")
                print(f"    Body:      {len(body_clean)} chars — {preview!r}...")
        else:
            p.write_text(new_content, encoding="utf-8")
            print(f"  MIGRATED: {p.name}")
            if aliases:
                print(f"    Aliases preserved: {aliases}")
            migrated.append(stem)

    print(f"\nDone: {len(migrated)} migrated, {len(skipped)} skipped (not in FastRover)")
    if skipped:
        print(f"  Skipped: {sorted(skipped)}")


if __name__ == "__main__":
    main()
