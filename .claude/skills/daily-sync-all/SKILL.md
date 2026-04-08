---
name: daily-sync-all
description: |
  Consolidated daily data sync with AI curation. Runs data sync from all
  sources (Gmail, Drive, Slack, Calendar, JIRA, GitHub PRs) then curates
  a Digest and Action Items section in today's daily note.
  Use this skill when the user wants to:
  - Run the daily sync (/daily-sync-all)
  - Sync all data sources and get a digest of what matters
  - See action items and highlights from today's information
  - Just sync data without curation ("just sync data", "sync only")
  - Just get a digest without re-syncing ("digest", "what's important", "curate")
---

# Daily Sync All Skill

Two modes:
- **Full run** (default): runs the sync script, which handles data sync, project tracking, and AI curation headlessly
- **Curation only** ("digest", "what's important", "curate"): skips sync, Claude curates directly

---

## Full Run

```bash
bash $VAULT_DIR/.claude/skills/daily-sync-all/scripts/sync_all_sources.sh
```

The script runs these steps and logs progress:
1. Ensure today's daily note exists
2. `pkm-sync sync --since 1d` — Gmail, Drive, Slack, Calendar, Jira
3. Calendar sync → updates Meetings table in daily note
4. JIRA + GitHub PR notes → `jira/` and `prs/` folders
5. Project sync → enriches `Projects/Work/` notes with related items
6. `pkm-sync index --since 1d` — update vector embeddings
7. `project-tracker` agent — Meeting Prep, Active Projects, Deadlines
8. `daily-curator` agent — writes `### Digest` and `### Action Items`

Logs: `~/Library/Logs/daily-work-sync/`

If the user said "sync only" / "just sync data", run the script with `--skip-index` or just
run it normally — steps 7 and 8 are agents and will run separately. Report any step failures
but don't stop on non-fatal errors.

---

## Curation Only

When the user asks for "digest", "what's important", or "curate" without wanting a full sync,
Claude curates the daily note directly without running the script.

### Step 1: Find today's daily note

```bash
obsidian daily:path
```

If the file doesn't exist: `bash .claude/skills/daily-sync-all/scripts/ensure_daily_note.sh`

### Step 2: Identify active projects

Read `Work Pipeline.md` from the vault root. Active projects are in **Early** and
**Mature** columns. Note their names and JIRA keys.

### Step 3: Scan for attention items

Check `jira/*.md` frontmatter for recently-updated issues (last 3 days).
Check `prs/*.md` for `has_unanswered_comments: true` or `ci_failed: true`.
Scan `Gmail/` for recent files, prioritizing: action, urgent, review, approve, decision.
Check today's meeting notes in `Meetings/YYYY/MM-Month/DD-Day/`.

For each active project keyword, run semantic search:
```bash
pkm-sync search "<keyword>" --limit 5
```

### Step 4: Write Digest and Action Items

**Digest** — 3–5 bullets grouped by category:
```markdown
### Digest

**Action Required**
- [[link]] Brief description

**Active Work Updates**
- [[link]] What changed

**New Information**
- [[link]] New context
```

**Action Items** — checkboxes, preserve existing `- [x]` completed items:
```markdown
### Action Items

- [ ] Respond to [[Gmail/some-email]] re: topic
- [ ] Fix CI on [[prs/hypershift-1234]]
```

Insert both sections after `### Meetings` and before `### Todo`. If they already exist,
replace in place (keep checked items at bottom).

---

## Launchd Integration

The script runs automatically every hour:
```
~/Library/LaunchAgents/com.user.daily-work-sync.plist
```
Logs: `~/Library/Logs/daily-work-sync/stdout.log` / `stderr.log`
