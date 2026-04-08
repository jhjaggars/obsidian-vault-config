---
name: obsidian-daily
description: |
  Work with today's Obsidian daily note using the CLI's native daily note commands.
  Use when the user wants to:
  - View today's daily note content
  - Append or prepend content to today's daily note
  - Get the file path of today's daily note
  - Open today's daily note in Obsidian's UI
  - Quickly add a todo item to today's note
  - Jot something down into the daily note
  For full daily sync with Gmail/Drive/Calendar/JIRA/GitHub, use the daily-sync-all skill instead.
---

# Obsidian Daily Note Skill

Quick daily note interactions via the Obsidian CLI. The CLI knows which file is "today's" daily note based on your Daily Notes plugin configuration — no need to construct the path manually.

**Requires**: Obsidian running with CLI registered. See `obsidian-cli` skill for setup.

---

## Commands

```bash
# Open today's daily note in Obsidian's UI
obsidian daily

# Get the file path of today's daily note
obsidian daily:path

# Read today's daily note content
obsidian daily:read

# Append content to the end of today's daily note
obsidian daily:append content="Content to add"

# Prepend content to the beginning of today's daily note
obsidian daily:prepend content="Content to add at top"
```

**Multiline content**: use `\n` for newlines:
```bash
obsidian daily:append content="## New Section\n\n- First item\n- Second item"
```

---

## This Vault's Daily Note Structure

Daily notes in this vault follow this section order:

```markdown
### Meetings

### Digest

### Action Items

### Todo

### Notes created today
...dataview block...

### Notes modified today
...dataview block...
```

**Important**: `daily:append` adds content at the very end of the file — after the dataview blocks. For section-aware insertion, use `daily:path` + Edit tool.

---

## Common Workflows

### Quick todo (section-aware — recommended)

```bash
# Step 1: Get the path
obsidian daily:path
# Returns: daily/2026/03-March/2026-03-02-Monday.md

# Step 2: Use Edit tool to insert under ### Todo
# Edit: find "### Todo\n" and append the new item after it
```

### Quick todo (fast — goes to end of file)

```bash
obsidian daily:append content="- [ ] Review the proposal"
```

Note: This lands after the dataview blocks. Fine for quick capture; move it under `### Todo` in Obsidian later if you prefer.

### Add a meeting link

```bash
# Section-aware (recommended):
# Step 1: Get path
obsidian daily:path
# Step 2: Edit tool → find "### Meetings\n" and insert "- [[Meetings/path/to/note]]"

# Quick append (goes to end):
obsidian daily:append content="- [[Meetings/2026/03-March/02-Monday/2026-03-02-Team Sync]]"
```

### Read today's note

```bash
obsidian daily:read
```

### Open in Obsidian UI

```bash
obsidian daily
```

### Check today's tasks

```bash
obsidian tasks daily
```

---

## CLI vs Direct Access for Daily Notes

| Need | Best Approach |
|------|--------------|
| Read the whole note | `obsidian daily:read` |
| Add content to specific section | `obsidian daily:path` → Edit tool |
| Quick append (section doesn't matter) | `obsidian daily:append content="..."` |
| Open in Obsidian | `obsidian daily` |
| View today's tasks | `obsidian tasks daily` |
| Full sync + AI digest | Use `daily-sync-all` skill |

---

## Relationship to Other Skills

- **`daily-sync-all`**: Full data sync (Gmail, Calendar, JIRA, GitHub) + AI-curated Digest and Action Items. Use for the full morning workflow.
- **`obsidian-daily`** (this skill): Quick ad-hoc interactions — jot a note, check content, add a todo. No sync, no curation.
- **`obsidian-vault-query`**: Search and analyze across all notes, including daily notes in bulk.

---

## Daily Note Path Format

This vault's daily notes follow:
```
daily/YYYY/MM-MonthName/YYYY-MM-DD-DayName.md
```

Example for today (2026-03-02):
```
daily/2026/03-March/2026-03-02-Monday.md
```

Use `obsidian daily:path` to get the exact path without computing it manually.
