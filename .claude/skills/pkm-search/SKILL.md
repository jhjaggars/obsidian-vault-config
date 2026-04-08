---
name: pkm-search
description: |
  Search all data synced by pkm-sync: Slack messages, Gmail, Calendar events, Jira issues,
  and Drive documents. Chooses the right search tool based on data type and query style.
  Use when the user wants to:
  - Find Slack messages by topic, channel, or author
  - Search Gmail by subject, sender, or content keywords
  - Find calendar events, Jira issues, or Drive docs by topic
  - Semantic/natural language search across all synced sources
  Triggers: "search my", "find in slack", "look for emails about", "did anyone mention",
  "what emails did I get about", "search pkm", "find messages about"
---

# PKM Search Skill

Unified search across all data sunk by pkm-sync. Each sink has its own search mechanism;
this skill picks the right one based on the data source and query type.

## Data Sources and Their Search Tools

| Source | Sink | Best Search Tool |
|--------|------|-----------------|
| Slack | `~/.config/pkm-sync/slack.db` | `pkm-sync search` (semantic) or `slack-search.py` (keyword/channel/author) |
| Gmail | `~/.config/pkm-sync/archive.db` | SQLite FTS4 (keyword) |
| Calendar | Obsidian vault (`Meetings/`) | `obsidian search` (see obsidian-vault-query skill) |
| Jira | Obsidian vault (`jira/`) | `obsidian search` or `pkm-sync search` (semantic) |
| Drive | Obsidian vault (`Drive/`) | `obsidian search` or Grep |

---

## Tool 1: Semantic Search — `pkm-sync search`

Natural language queries across all indexed sources. Best for conceptual topics where you
don't know exact keywords ("meetings where we discussed scaling problems").

```bash
# Search all sources
pkm-sync search "autoscaling edge cases" --limit 10

# Filter by source type
pkm-sync search "fips compliance" --source-type slack
pkm-sync search "release announcement" --source-type gmail
pkm-sync search "sprint planning" --source-type google_calendar
pkm-sync search "blocked deployment" --source-type jira

# Filter by specific source instance
pkm-sync search "quarterly review" --source-name gmail_work
pkm-sync search "team discussion" --source-name slack_mycompany

# Tune results
pkm-sync search "incident response" --limit 20 --min-score 0.65

# JSON output for programmatic use
pkm-sync search "rosa nodepool" --format json --limit 5
```

**Flags:**
- `--source-type` — filter by type: `gmail`, `slack`, `google_calendar`, `jira`
- `--source-name` — filter by instance name from your pkm-sync config (e.g., `gmail_work`, `slack_mycompany`, `jira_work`)
- `--limit` — max results (default 10)
- `--min-score` — similarity threshold 0.0–1.0 (higher = stricter; 0.6–0.7 is useful)
- `--format` — `text` (default) or `json`

**Note:** Semantic search requires embeddings to be indexed. Run `pkm-sync index --since 7d`
if results are sparse. Currently Slack is most thoroughly indexed.

---

## Tool 2: Gmail Keyword Search — `email_search.py`

A Python wrapper around `archive.db` that handles the FTS4 JOIN complexity and returns
clean, LLM-friendly output. Prefer this over raw SQLite for most email searches.

```bash
SCRIPT=".claude/skills/pkm-search/email_search.py"

# FTS4 keyword search (subject + body + from_addr)
python3 $SCRIPT "autoscaling FIPS"

# Filter by sender (substring match)
python3 $SCRIPT --from redhat.com --since 2026-01-01

# Include body text in output
python3 $SCRIPT "approval" --body --limit 5

# JSON output for agent/programmatic use
python3 $SCRIPT "deployment" --format json --body --limit 5

# Combine FTS query with filters
python3 $SCRIPT "ServiceNow" --from servicedesk --since 2026-03-01

# List recent messages from a sender (no FTS query needed)
python3 $SCRIPT --from alice@example.com --since 2026-03-01
```

**Flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `<query>` | (optional) | FTS4 MATCH query string |
| `--from` | "" | Filter sender (substring LIKE match) |
| `--since` | "" | Filter by date_sent >= YYYY-MM-DD |
| `--limit` | 10 | Max results |
| `--format` | text | `text` or `json` |
| `--body` | false | Include body text (first 200 chars in text mode; full in JSON) |
| `--db` | `~/.config/pkm-sync/archive.db` | Override DB path |

**Implementation notes:**
- Body text lives in `messages_fts_content.c1body` (joined via `docid = messages.rowid`),
  not in the `messages` table — `email_search.py` handles this automatically
- `to_addrs` and `cc_addrs` are JSON arrays in the DB; the script parses them
- At least one of `<query>`, `--from`, or `--since` is required

**For raw SQLite when needed** (e.g. labels, counts, custom queries):

```bash
# Check unread/labeled
sqlite3 ~/.config/pkm-sync/archive.db \
  "SELECT subject, from_addr, date_sent, labels FROM messages
   WHERE labels LIKE '%UNREAD%'
   ORDER BY date_sent DESC LIMIT 10;"

# Count by source
sqlite3 ~/.config/pkm-sync/archive.db \
  "SELECT source_name, COUNT(*) FROM messages GROUP BY source_name;"
```

**Schema:**
- `messages`: `gmail_id`, `thread_id`, `subject`, `from_addr`, `to_addrs`, `cc_addrs`,
  `date_sent`, `labels` (JSON array), `has_attachments`, `source_name`
- `messages_fts`: virtual FTS4 table on `subject`, `body`, `from_addr`
- `messages_fts_content`: raw content table; `c1body` = email body text

---

## Tool 3: Slack Structured Search — SQLite

For channel-specific, author-specific, or recent Slack messages. Use direct SQLite queries
on `slack.db` for structured filtering; use `pkm-sync search` for semantic queries.

```bash
# Keyword search in a specific channel
sqlite3 ~/.config/pkm-sync/slack.db \
  "SELECT channel_name, author, content, created_at
   FROM slack_messages
   WHERE channel_name LIKE '%hypershift%'
     AND content LIKE '%autoscaling%'
   ORDER BY created_at DESC LIMIT 20;"

# Filter by author, last 7 days
sqlite3 ~/.config/pkm-sync/slack.db \
  "SELECT channel_name, author, content, created_at
   FROM slack_messages
   WHERE author LIKE '%your_username%'
     AND created_at >= datetime('now', '-7 days')
   ORDER BY created_at DESC LIMIT 20;"

# Thread root messages only (find conversation starters)
sqlite3 ~/.config/pkm-sync/slack.db \
  "SELECT channel_name, author, content, reply_count, created_at
   FROM slack_messages
   WHERE is_thread_root = 1 AND content LIKE '%FIPS%'
   ORDER BY created_at DESC LIMIT 10;"

# Messages from multiple channels
sqlite3 ~/.config/pkm-sync/slack.db \
  "SELECT channel_name, author, content, created_at
   FROM slack_messages
   WHERE channel_name IN ('team-your-channel', 'eng-architecture')
     AND created_at >= datetime('now', '-3 days')
   ORDER BY created_at DESC LIMIT 30;"
```

**Schema:** `slack_messages`: `id`, `channel_id`, `channel_name`, `workspace`, `author`,
`content`, `message_url`, `item_type`, `thread_ts`, `is_thread_root`, `reply_count`,
`created_at`

---

## Tool 4: Calendar / Jira / Drive — Obsidian Vault Search

Calendar events, Jira issues, and Drive docs are exported as markdown to the vault.
Use the Obsidian CLI or grep (see `obsidian-vault-query` skill for full reference).

```bash
# Calendar: search meeting notes
obsidian search query="hypershift review" path="Meetings/"

# Jira: search issues by keyword or status
obsidian search query="status:In Progress" path="jira/"
obsidian search query="autoscaling" path="jira/"

# Drive: search documents
obsidian search query="ROSA architecture" path="Drive/"

# Combine semantic search with vault lookup:
# 1. Find relevant item via pkm-sync search
pkm-sync search "rosa nodepool capacity" --source-type jira --format json
# 2. Use the returned title/key to find the note
obsidian search query="PROJ-447" path="jira/"
```

---

## Decision Guide: Which Tool to Use

```
Is it Slack?
  → Natural language / conceptual topic  →  pkm-sync search --source-type slack
  → Specific channel or author           →  slack-search.py --channel / --author
  → Recent activity in a channel         →  slack-search.py --days 7 --channel "..."

Is it Gmail?
  → Know exact words in subject/body     →  email_search.py "<query>"
  → Know the sender / date range         →  email_search.py --from <addr> --since <date>
  → Need body text                       →  email_search.py "<query>" --body
  → Need labels, counts, custom SQL      →  raw sqlite3 archive.db
  → Conceptual / can't recall keywords   →  pkm-sync search --source-type gmail

Is it Calendar / Jira / Drive?
  → Synced to vault as markdown          →  obsidian search path="Meetings/"  (or jira/, Drive/)
  → Conceptual topic, not sure where     →  pkm-sync search --source-type google_calendar / jira

Cross-source (don't know where info is)?
  → pkm-sync search "<query>"  (searches all indexed sources)
```

---

## Database Paths

| Database | Path |
|----------|------|
| Vector DB (semantic index) | `~/.config/pkm-sync/vectors.db` |
| Email archive | `~/.config/pkm-sync/archive.db` |
| Slack archive | `~/.config/pkm-sync/slack.db` |
| Slack search script | `~/.config/pkm-sync/slack-search.py` |

The vector DB path is configured in `~/.config/pkm-sync/config.yaml` under `vectordb.db_path`.
