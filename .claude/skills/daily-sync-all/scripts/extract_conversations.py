#!/usr/bin/env python3
# /// script
# dependencies = []
# ///
"""
Extract today's conversations from Slack DMs and Gmail EML files.
Outputs a JSON file path to stdout for use by the conversation-summarizer agent.

Usage:
    uv run extract_conversations.py [vault_dir] [date_YYYY-MM-DD]
"""

import email as email_mod
import email.policy
import json
import os
import re
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path


SLACK_DB = Path.home() / ".config/pkm-sync/slack.db"
ARCHIVE_DB = Path.home() / ".config/pkm-sync/archive.db"
EML_DIR = Path.home() / ".config/pkm-sync/archive/eml/work-gmail"

MY_NAME = os.environ.get("PKM_USER_NAME", "")
MY_EMAIL = os.environ.get("PKM_USER_EMAIL", "")
MY_EMAIL_ALT = os.environ.get("PKM_USER_EMAIL_ALT", "")

# Slack username (the part before @ in your email, used in mpdm channel names)
_MY_SLACK_USER = MY_EMAIL.split("@")[0] if "@" in MY_EMAIL else ""

# Automated sender patterns to skip (case-insensitive substrings in From address)
AUTOMATED_FROM_PATTERNS = [
    "noreply",
    "no-reply",
    "jira@",
    "docs.google.com",
    "calendar-notification",
    "bounces.google.com",
    "doclist.bounces",
    "notifications@github.com",
    "reply.github.com",
    "github.com",
    "atlassian.net",
    "google.com",
    "redhat.com/updates",
    "accounts.google.com",
    "drive-shares",
    "comments-noreply",
    "donotreply",
    "auto-confirm",
    "automated",
    "mailchimp",
    "sendgrid",
    "amazonses",
    "servicedesk",
]

# Mailing list / broadcast patterns in To/Cc (skip if these are the primary recipient)
MAILING_LIST_PATTERNS = [
    "-list@",
    "-strategy@",
    "-community@",
    "all-redhat",
    "rdu-list",
    "cloud-strategy",
    "openshift-leads",
    "-announce@",
]

# Slack channel prefixes that are NOT DMs (all lowercase-hyphen channels)
# DM channels have proper names with spaces and uppercase letters
def is_dm_channel(channel_name: str) -> bool:
    """DM channels are person names: contain uppercase and spaces, not hyphen-based."""
    return bool(re.search(r'[A-Z]', channel_name)) and ' ' in channel_name


def extract_slack_conversations(target_date: str) -> list[dict]:
    """Extract DM and MPDM conversations + notable public thread exchanges from Slack."""
    if not SLACK_DB.exists():
        print(f"WARNING: Slack DB not found at {SLACK_DB}", file=sys.stderr)
        return []

    conversations = []

    with sqlite3.connect(SLACK_DB) as conn:
        conn.row_factory = sqlite3.Row

        # 1. 1:1 DMs (channel_name is a person's display name)
        rows = conn.execute("""
            SELECT channel_name, author, content, created_at, thread_ts, message_url
            FROM slack_messages
            WHERE date(created_at) = ?
              AND channel_name != ?
            ORDER BY channel_name, created_at
        """, (target_date, MY_NAME)).fetchall()

        dm_channels = {}
        for row in rows:
            ch = row["channel_name"]
            if not is_dm_channel(ch):
                continue
            if ch not in dm_channels:
                dm_channels[ch] = []
            dm_channels[ch].append({
                "author": row["author"],
                "content": row["content"],
                "time": row["created_at"],
            })

        for person, messages in dm_channels.items():
            if len(messages) < 3:
                continue
            # Cap at 50 messages: first 10 + last 40
            if len(messages) > 50:
                messages = messages[:10] + messages[-40:]
            conversations.append({
                "type": "dm",
                "person": person,
                "message_count": len(messages),
                "messages": messages,
            })

        # Sort DMs by message count descending
        conversations.sort(key=lambda c: c["message_count"], reverse=True)

        # 2. Group DMs (mpdm- channels where this user appears)
        mpdm_pattern = f"mpdm-%{_MY_SLACK_USER}%" if _MY_SLACK_USER else "mpdm-%"
        mpdm_rows = conn.execute("""
            SELECT channel_name, author, content, created_at
            FROM slack_messages
            WHERE date(created_at) = ?
              AND channel_name LIKE ?
            ORDER BY channel_name, created_at
        """, (target_date, mpdm_pattern)).fetchall()

        mpdm_channels = {}
        for row in mpdm_rows:
            ch = row["channel_name"]
            if ch not in mpdm_channels:
                mpdm_channels[ch] = []
            mpdm_channels[ch].append({
                "author": row["author"],
                "content": row["content"],
                "time": row["created_at"],
            })

        for channel_name, messages in mpdm_channels.items():
            if len(messages) < 3:
                continue
            # Parse participant names from mpdm channel name
            # Format: mpdm-user1--user2--user3-N
            inner = re.sub(r'^mpdm-', '', channel_name)
            inner = re.sub(r'-\d+$', '', inner)
            usernames = [u for u in inner.split('--') if u and u != _MY_SLACK_USER]

            if len(messages) > 50:
                messages = messages[:10] + messages[-40:]

            # Get distinct authors from messages (actual display names)
            authors = list({m["author"] for m in messages if m["author"] != MY_NAME})

            conversations.append({
                "type": "mpdm",
                "channel": channel_name,
                "participants": authors,
                "usernames": usernames,
                "message_count": len(messages),
                "messages": messages,
            })

        # 3. Public channel threads where Jesse sent 2+ messages
        thread_rows = conn.execute("""
            SELECT s.channel_name, s.thread_ts,
                   COUNT(CASE WHEN s.author = ? THEN 1 END) as jesse_count,
                   COUNT(*) as total_count,
                   GROUP_CONCAT(DISTINCT s.author) as authors
            FROM slack_messages s
            WHERE date(s.created_at) = ?
              AND s.thread_ts IS NOT NULL
              AND s.thread_ts != ''
              AND s.author = ?
              AND s.channel_name NOT LIKE 'mpdm-%'
              AND NOT (? || ? IN (
                SELECT channel_name FROM slack_messages WHERE channel_name = s.channel_name AND channel_name LIKE '% %' LIMIT 1
              ))
            GROUP BY s.channel_name, s.thread_ts
            HAVING jesse_count >= 2
            ORDER BY jesse_count DESC
            LIMIT 5
        """, (MY_NAME, target_date, MY_NAME, '', '')).fetchall()

        # Simpler thread query
        thread_rows = conn.execute("""
            SELECT channel_name, thread_ts,
                   SUM(CASE WHEN author = ? THEN 1 ELSE 0 END) as jesse_count,
                   COUNT(*) as total_count
            FROM slack_messages
            WHERE date(created_at) = ?
              AND thread_ts IS NOT NULL AND thread_ts != ''
              AND channel_name NOT LIKE 'mpdm-%'
            GROUP BY channel_name, thread_ts
            HAVING jesse_count >= 2
            ORDER BY jesse_count DESC
            LIMIT 5
        """, (MY_NAME, target_date)).fetchall()

        for row in thread_rows:
            ch = row["channel_name"]
            # Skip if this is a DM channel (already handled above)
            if is_dm_channel(ch):
                continue
            thread_ts = row["thread_ts"]
            thread_msgs = conn.execute("""
                SELECT author, content, created_at
                FROM slack_messages
                WHERE channel_name = ? AND thread_ts = ?
                ORDER BY created_at
            """, (ch, thread_ts)).fetchall()

            authors = list({m["author"] for m in thread_msgs if m["author"] != MY_NAME})
            messages = [{"author": m["author"], "content": m["content"], "time": m["created_at"]} for m in thread_msgs]

            conversations.append({
                "type": "thread",
                "channel": ch,
                "participants": authors,
                "message_count": len(messages),
                "messages": messages,
            })

    return conversations


def is_automated_sender(from_addr: str) -> bool:
    """Return True if the From address looks automated/non-human."""
    from_lower = from_addr.lower()
    return any(p in from_lower for p in AUTOMATED_FROM_PATTERNS)


def is_mailing_list_to(to_str: str) -> bool:
    """Return True if the primary To address is a mailing list."""
    to_lower = to_str.lower() if to_str else ""
    return any(p in to_lower for p in MAILING_LIST_PATTERNS)


def extract_display_name(addr: str) -> str:
    """Extract display name from 'Name <email>' or return email local part."""
    addr = addr.strip()
    m = re.match(r'^"?([^"<]+?)"?\s*<[^>]+>$', addr)
    if m:
        return m.group(1).strip()
    # Just an email address
    m = re.match(r'^([^@]+)@', addr)
    if m:
        return m.group(1)
    return addr


def get_email_body(msg) -> str:
    """Extract plain text body from email message, up to 300 chars."""
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                try:
                    body = part.get_content()
                    break
                except Exception:
                    pass
    else:
        try:
            body = msg.get_content()
        except Exception:
            pass
    # Clean up
    body = re.sub(r'\r?\n', ' ', body or "")
    body = re.sub(r'\s+', ' ', body).strip()
    # Strip quoted reply blocks (lines starting with >)
    body = re.sub(r'>+[^\n]*', '', body).strip()
    return body[:300]


def extract_email_conversations(target_date: str) -> list[dict]:
    """Extract real person-to-person email conversations from EML files."""
    if not ARCHIVE_DB.exists() or not EML_DIR.exists():
        print(f"WARNING: Email archive not found", file=sys.stderr)
        return []

    # Get gmail_ids for today's emails from the archive DB
    with sqlite3.connect(ARCHIVE_DB) as conn:
        rows = conn.execute("""
            SELECT gmail_id FROM messages
            WHERE date(date_sent) = ?
            ORDER BY date_sent
        """, (target_date,)).fetchall()

    gmail_ids = [r[0] for r in rows]
    if not gmail_ids:
        return []

    # Group email exchanges by person
    person_emails: dict[str, list[dict]] = {}

    for gmail_id in gmail_ids:
        eml_path = EML_DIR / f"{gmail_id}.eml"
        if not eml_path.exists():
            continue

        try:
            with open(eml_path, "rb") as f:
                msg = email_mod.message_from_binary_file(f, policy=email_mod.policy.default)
        except Exception as e:
            print(f"WARNING: could not parse {eml_path}: {e}", file=sys.stderr)
            continue

        from_addr = msg.get("From", "")
        to_addr = msg.get("To", "")
        cc_addr = msg.get("Cc", "")
        subject = msg.get("Subject", "")
        date_str = msg.get("Date", "")

        # Skip automated senders
        if is_automated_sender(from_addr):
            continue

        # Skip mailing lists
        i_am_to = (bool(MY_EMAIL) and MY_EMAIL in to_addr) or (bool(MY_EMAIL_ALT) and MY_EMAIL_ALT in to_addr)
        if is_mailing_list_to(to_addr) and not i_am_to:
            continue

        from_lower = from_addr.lower()
        is_from_me = bool(MY_EMAIL) and MY_EMAIL in from_lower or bool(MY_EMAIL_ALT) and MY_EMAIL_ALT in from_lower

        # Determine the other person in the conversation
        if is_from_me:
            # I sent it — the other person is in To
            other_addr = to_addr
        else:
            # Someone sent to me — they are the other person
            other_addr = from_addr

        if not other_addr:
            continue

        # Skip if the other person is also automated or a list
        if is_automated_sender(other_addr) or is_mailing_list_to(other_addr):
            continue

        # Skip calendar notification subjects
        subject_lower = subject.lower()
        if any(p in subject_lower for p in [
            "accepted:", "declined:", "invitation:", "updated invitation:", "cancelled:",
            "canceled event", "notification subject:", "slo report", "weekly ",
        ]):
            continue

        person_name = extract_display_name(other_addr)

        # Skip if person name looks non-human (single word, no space = company/bot)
        if ' ' not in person_name and not re.match(r'^[A-Z][a-z]', person_name):
            continue

        body_snippet = get_email_body(msg)

        entry = {
            "subject": subject,
            "body_snippet": body_snippet,
            "date": date_str,
            "from_me": is_from_me,
        }

        if person_name not in person_emails:
            person_emails[person_name] = []
        person_emails[person_name].append(entry)

    # Build conversation objects
    email_convos = []
    for person, emails in person_emails.items():
        if not emails:
            continue
        # Only include threads where Jesse actually sent a message
        if not any(e["from_me"] for e in emails):
            continue
        email_convos.append({
            "type": "email",
            "person": person,
            "message_count": len(emails),
            "messages": emails,
        })

    return email_convos


def main():
    vault_dir = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("VAULT_DIR", "")
    target_date = sys.argv[2] if len(sys.argv) > 2 else date.today().isoformat()

    staging_dir = Path(vault_dir) / ".claude/skills/daily-sync-all/staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    output_path = staging_dir / f"conversations-{target_date}.json"

    print(f"Extracting conversations for {target_date}...", file=sys.stderr)

    slack_convos = extract_slack_conversations(target_date)
    email_convos = extract_email_conversations(target_date)

    all_convos = slack_convos + email_convos

    payload = {
        "date": target_date,
        "extracted_at": datetime.now().isoformat(),
        "conversations": all_convos,
    }

    with open(output_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    total = len(all_convos)
    slack_count = sum(1 for c in all_convos if c["type"] in ("dm", "mpdm", "thread"))
    email_count = sum(1 for c in all_convos if c["type"] == "email")
    print(f"Extracted {total} conversations ({slack_count} Slack, {email_count} email)", file=sys.stderr)

    # Print path to stdout for the pipeline to capture
    print(output_path)


if __name__ == "__main__":
    main()
