#!/usr/bin/env python3
"""Normalize attendee frontmatter in pkm-sync meeting notes.

Converts email-based attendees like [[alice@example.com]] to People page
names like [[Alice Smith]]. Also removes self-references (set PKM_USER_EMAIL).

Usage:
    python3 normalize_attendees.py <directory_or_file> [<file2> ...]
    python3 normalize_attendees.py Meetings/2026/

Designed to run after pkm-sync sync, before calendar table sync.
"""

import os
import re
import sys
from pathlib import Path

VAULT_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).parent))

from sync_calendar import build_people_index

SELF_EMAIL = os.environ.get("PKM_USER_EMAIL", "")


def resolve_email(email: str, people_index: dict) -> str | None:
    """Try to resolve an email address to a People page wiki-link.

    Returns '[[Person Name]]' if resolved, None if no match.
    Uses the same matching logic as sync_calendar.py:format_attendees().
    """
    prefix = email.split("@")[0].lower()

    # Exact prefix match (e.g., asmith → Alice Smith)
    if prefix in people_index["by_prefix"]:
        return f"[[{people_index['by_prefix'][prefix]}]]"

    # Fuzzy prefix: prefix.startswith(known_prefix) with len >= 4
    # Handles suffixes like vkarehfa → vkareh → Victor Kareh
    best_match = None
    best_len = 0
    for known_prefix, page in people_index["by_prefix"].items():
        if (
            prefix.startswith(known_prefix)
            and len(known_prefix) >= 4
            and len(known_prefix) > best_len
        ):
            best_match = page
            best_len = len(known_prefix)
    if best_match:
        return f"[[{best_match}]]"

    # Surname suffix: email prefix ends with a known surname (e.g., kbsingh → singh)
    if "by_surname" in people_index:
        for surname, pages in people_index["by_surname"].items():
            if len(pages) == 1 and len(surname) >= 4 and prefix.endswith(surname):
                return f"[[{pages[0]}]]"

    return None


def normalize_file(path: Path, people_index: dict) -> tuple[bool, list[str], list[str]]:
    """Normalize attendees in a single file's frontmatter.

    Returns (was_modified, resolved_items, unresolved_emails).
    """
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"  ERROR reading {path}: {e}", file=sys.stderr)
        return False, [], []

    # Must have frontmatter
    fm_match = re.match(r"^(---\n)(.*?)(---\n)", content, re.DOTALL)
    if not fm_match:
        return False, [], []

    frontmatter = fm_match.group(2)
    if "attendees:" not in frontmatter:
        return False, [], []

    resolved = []
    unresolved = []
    fm_lines = frontmatter.split("\n")
    new_fm_lines = []
    in_attendees = False

    for line in fm_lines:
        # Detect start of attendees block
        if re.match(r"^attendees:", line):
            in_attendees = True
            new_fm_lines.append(line)
            continue

        if in_attendees:
            # A non-indented, non-empty line ends the attendees block
            if line and not line.startswith(" ") and not line.startswith("\t"):
                in_attendees = False
                new_fm_lines.append(line)
                continue

            # Look for an email wiki-link on this line
            email_match = re.search(
                r'\[\[([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+)\]\]', line
            )
            if email_match:
                email = email_match.group(1)

                # Drop self-reference
                if email.lower() == SELF_EMAIL.lower():
                    resolved.append(f"removed self ({email})")
                    continue  # skip line entirely

                # Attempt resolution
                wiki = resolve_email(email, people_index)
                if wiki:
                    # Replace the quoted [[email]] with quoted [[Name]]
                    new_line = re.sub(
                        r'"?\[\[' + re.escape(email) + r'\]\]"?',
                        f'"{wiki}"',
                        line,
                    )
                    new_fm_lines.append(new_line)
                    resolved.append(f"{email} → {wiki}")
                else:
                    new_fm_lines.append(line)
                    unresolved.append(email)
            else:
                new_fm_lines.append(line)
        else:
            new_fm_lines.append(line)

    new_frontmatter = "\n".join(new_fm_lines)
    if new_frontmatter == frontmatter:
        return False, [], []

    # Reconstruct full file content
    new_content = (
        fm_match.group(1)
        + new_frontmatter
        + fm_match.group(3)
        + content[fm_match.end():]
    )

    try:
        path.write_text(new_content, encoding="utf-8")
    except Exception as e:
        print(f"  ERROR writing {path}: {e}", file=sys.stderr)
        return False, [], []

    return True, resolved, unresolved


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
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <directory_or_file> [<file2> ...]")
        sys.exit(1)

    people_index = build_people_index(VAULT_ROOT)

    files = collect_files(sys.argv[1:])
    if not files:
        print("No files found.")
        return

    modified_count = 0
    all_unresolved: set[str] = set()

    for f in files:
        was_modified, resolved, unresolved = normalize_file(f, people_index)
        if was_modified:
            modified_count += 1
            print(f"  {f.relative_to(VAULT_ROOT)}")
            for r in resolved:
                print(f"    + {r}")
        all_unresolved.update(unresolved)

    print(f"\nDone: {modified_count}/{len(files)} files modified")
    if all_unresolved:
        print(f"Unresolved emails (no People page match): {sorted(all_unresolved)}")


if __name__ == "__main__":
    main()
