#!/usr/bin/env python3
"""Sync calendar events to daily note."""

import json
import os
import sys
from pathlib import Path
from datetime import datetime
import re


def build_people_index(vault_root: Path) -> dict:
    """Build lookup indexes from People/*.md filenames.

    Returns a dict with two indexes:
      'by_name': {lowercase full name: stem}  e.g. {'victor kareh': 'Victor Kareh'}
      'by_prefix': {lowercase email-style prefix: stem}  e.g. {'vkareh': 'Victor Kareh'}
    """
    people_dir = vault_root / "People"
    index = {"by_name": {}, "by_prefix": {}}

    if not people_dir.is_dir():
        return index

    for p in people_dir.glob("*.md"):
        stem = p.stem  # e.g. "Victor Kareh"
        index["by_name"][stem.lower()] = stem

        # Build email-style prefixes: first-initial + last-name variants
        parts = stem.split()
        if len(parts) >= 2:
            first = parts[0]
            last = parts[-1]
            # Common email patterns: vkareh, vkarehfa (with suffix), victorkareh
            prefix1 = (first[0] + last).lower()             # vkareh
            prefix2 = (first + last).lower()                 # victorkareh
            prefix3 = (first[0] + last[:4]).lower()          # vkare
            prefix4 = (first[:2] + last).lower()             # majones
            index["by_prefix"][prefix1] = stem
            index["by_prefix"][prefix2] = stem
            index["by_prefix"][prefix3] = stem
            index["by_prefix"][prefix4] = stem

    # Build surname index: {lowercase surname: [stems]}
    # Used as last-resort matching for aliases like "KB Singh" → "Karanbir Singh"
    surname_map = {}
    for stem in index["by_name"].values():
        parts = stem.split()
        if len(parts) >= 2:
            surname = parts[-1].lower()
            surname_map.setdefault(surname, []).append(stem)
    index["by_surname"] = surname_map

    return index


def wikilink_name(display_name: str, people_index: dict) -> str:
    """Convert a display name to a wiki-link if a matching People page exists.

    Returns '[[Page Name]]' or '[[Page Name\\|Display Name]]' if aliased,
    or the plain display name if no match.

    Pipe characters are escaped as \\| so links are safe inside markdown tables.
    """
    name_lower = display_name.strip().lower()

    # Direct match by full name
    if name_lower in people_index["by_name"]:
        page = people_index["by_name"][name_lower]
        if page.lower() == name_lower:
            return f"[[{page}]]"
        else:
            return f"[[{page}\\|{display_name.strip()}]]"

    # Try email-prefix match (for names derived from email usernames)
    prefix = re.sub(r'[^a-z]', '', name_lower)
    if prefix in people_index["by_prefix"]:
        page = people_index["by_prefix"][prefix]
        return f"[[{page}\\|{display_name.strip()}]]"

    # Try surname match: if the last word of display_name matches exactly one
    # People page surname, use that (handles "KB Singh" → "Karanbir Singh")
    display_parts = display_name.strip().split()
    if len(display_parts) >= 2 and "by_surname" in people_index:
        surname = display_parts[-1].lower()
        matches = people_index["by_surname"].get(surname, [])
        if len(matches) == 1:
            page = matches[0]
            return f"[[{page}\\|{display_name.strip()}]]"

    # No match — return plain name
    return display_name.strip()

def sanitize_title(title: str) -> str:
    """Sanitize title for use in filename."""
    # Replace problematic characters
    replacements = {
        '/': '-',
        '\\': '-',
        ':': '-',
        '*': '',
        '?': '',
        '"': '',
        '<': '',
        '>': '',
        '|': '-',
    }
    result = title
    for old, new in replacements.items():
        result = result.replace(old, new)
    return result.strip()

def format_attendees(attendees: list, people_index: dict = None) -> str:
    """Format attendees list, filtering out the user and resources.

    If people_index is provided, attendee names are wiki-linked to matching
    People pages in the vault.
    """
    if not attendees:
        return ""

    if people_index is None:
        people_index = {"by_name": {}, "by_prefix": {}}

    # Filter out the user and calendar resources
    # Set PKM_USER_EMAIL env var to remove yourself from attendee lists
    _self_email = os.environ.get("PKM_USER_EMAIL", "")
    filtered = [
        a for a in attendees
        if (not _self_email or a['Email'] != _self_email)
        and not a['Email'].endswith('@resource.calendar.google.com')
        and not a['Email'].endswith('@group.calendar.google.com')
    ]

    # Get names, preferring DisplayName over email
    names = []
    for attendee in filtered:
        if attendee.get('DisplayName'):
            display = attendee['DisplayName']
        else:
            # Extract name from email (part before @)
            display = attendee['Email'].split('@')[0]

        # Try wiki-linking via display name first
        linked = wikilink_name(display, people_index)

        # If no match on display name and we have an email, try email prefix
        if linked == display.strip() and attendee.get('Email'):
            prefix = attendee['Email'].split('@')[0].lower()
            if prefix in people_index["by_prefix"]:
                page = people_index["by_prefix"][prefix]
                linked = f"[[{page}\\|{display.strip()}]]"
            else:
                # Try fuzzy prefix match: check if any known prefix is a
                # prefix of the email username (handles suffixes like
                # vkarehfa matching vkareh for Victor Kareh)
                best_match = None
                best_len = 0
                for known_prefix, page in people_index["by_prefix"].items():
                    if (prefix.startswith(known_prefix)
                            and len(known_prefix) >= 4
                            and len(known_prefix) > best_len):
                        best_match = page
                        best_len = len(known_prefix)
                if best_match:
                    linked = f"[[{best_match}\\|{display.strip()}]]"
                elif "by_surname" in people_index:
                    # Last resort: check if a known surname appears at
                    # the end of the email prefix (e.g., kbsingh → singh
                    # → Karanbir Singh if unique)
                    for surname, pages in people_index["by_surname"].items():
                        if (len(pages) == 1
                                and len(surname) >= 4
                                and prefix.endswith(surname)):
                            linked = f"[[{pages[0]}\\|{display.strip()}]]"
                            break

        names.append(linked)

    # Limit to first 5 attendees to keep table readable
    if len(names) > 5:
        return ", ".join(names[:5]) + f" (+{len(names) - 5} more)"

    return ", ".join(names)

def find_gemini_transcript(event: dict) -> dict:
    """Find Gemini transcript in event attachments."""
    if not event.get('attachments'):
        return None

    for attachment in event['attachments']:
        title = attachment.get('Title', '')
        if 'Notes by Gemini' in title or 'Gemini' in title:
            return {
                'url': attachment.get('FileURL'),
                'file_id': attachment.get('FileID'),
                'title': title
            }
    return None

def format_meeting_row(event: dict, date_str: str, day_name: str, people_index: dict = None) -> tuple:
    """Format event as a table row."""
    title = event['summary']
    sanitized_title = sanitize_title(title)

    # Parse start time
    start_time = datetime.fromisoformat(event['start_time'])
    time_str = start_time.strftime('%I:%M %p').lstrip('0')  # Remove leading zero from hour

    # Extract just the date parts for the path
    # Format: Meetings/2026/02-February/17-Tuesday/2026-02-17-Title.md
    year = date_str[:4]
    month_num = date_str[5:7]
    day_num = date_str[8:10]

    # Month name mapping
    months = {
        '01': 'January', '02': 'February', '03': 'March', '04': 'April',
        '05': 'May', '06': 'June', '07': 'July', '08': 'August',
        '09': 'September', '10': 'October', '11': 'November', '12': 'December'
    }
    month_name = months[month_num]

    path = f"Meetings/{year}/{month_num}-{month_name}/{day_num}-{day_name}/{date_str}-{sanitized_title}.md"

    # Wiki-link — escape any | in the display title so it doesn't break markdown tables
    display_title = title.replace('|', r'\|')
    link = f"[[{path}\\|{display_title}]]"

    # Format attendees
    attendees = format_attendees(event.get('attendees', []), people_index)

    # Check for Gemini transcript
    transcript = find_gemini_transcript(event)
    transcript_link = ""
    if transcript:
        transcript_path = f"Meetings/{year}/{month_num}-{month_name}/{day_num}-{day_name}/{date_str}-{sanitized_title}.md"
        transcript_link = f"[[{transcript_path}\\|📝]]"

    return (time_str, link, attendees, transcript_link, transcript)

def main():
    # Build People page index for wiki-linking attendees
    # Vault root: script lives at .claude/skills/calendar-sync-lib/, or pass as first CLI arg
    if len(sys.argv) > 1:
        vault_root = Path(sys.argv[1])
    else:
        vault_root = Path(__file__).resolve().parents[3]
    people_index = build_people_index(vault_root)

    # Read JSON from stdin
    events = json.load(sys.stdin)

    # Sort events by start time
    events.sort(key=lambda e: e['start_time'])

    # Determine today's date dynamically
    # If events exist, use the date from the first event, otherwise use system date
    if events:
        first_event_time = datetime.fromisoformat(events[0]['start_time'])
        date_str = first_event_time.strftime('%Y-%m-%d')
        day_name = first_event_time.strftime('%A')
    else:
        # No events, use today's date
        today = datetime.now()
        date_str = today.strftime('%Y-%m-%d')
        day_name = today.strftime('%A')

    # Format as table
    rows = []
    transcripts_to_fetch = []

    for event in events:
        row = format_meeting_row(event, date_str, day_name, people_index)
        time_str, link, attendees, transcript_link, transcript = row
        rows.append((time_str, link, attendees, transcript_link))

        if transcript:
            transcripts_to_fetch.append({
                'url': transcript['url'],
                'title': event['summary'],
                'sanitized_title': sanitize_title(event['summary']),
                'date': date_str
            })

    # Output markdown table
    print("| Time | Meeting | Attendees | Transcript |")
    print("| ---- | ------- | --------- | ---------- |")
    for time_str, link, attendees, transcript_link in rows:
        print(f"| {time_str} | {link} | {attendees} | {transcript_link} |")

    # Output transcript URLs to stderr for processing
    if transcripts_to_fetch:
        print("\n---TRANSCRIPTS---", file=sys.stderr)
        print(json.dumps(transcripts_to_fetch, indent=2), file=sys.stderr)

if __name__ == '__main__':
    main()
