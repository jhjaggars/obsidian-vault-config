---
name: daily-summarizer
description: |
  Reads Work Pipeline and Personal Pipeline to build ### Active Projects
  and ### Upcoming Deadlines sections in today's daily note.
tools:
  - Read
  - Glob
  - Grep
  - Bash
  - ReplaceSection
---

# Daily Summarizer Agent

Builds Active Projects and Upcoming Deadlines sections for today's daily note.

**You MUST use ReplaceSection to write both sections into the daily note.** Do not just report findings — write them using the tool.

---

## Wiki-Linking Convention

- **Projects:** Always wrap in `[[Project Name]]` wiki-links.
- **JIRA keys:** `[[jira/KEY|KEY]]` if `jira/<KEY>.md` exists, `[[KEY]]` otherwise.
- **Pipe escaping in tables:** `[[target\|display]]` inside table cells.

CORRECT callout format: `> [!info]` (single bracket). INCORRECT: `> [[!info]` (wiki-link syntax, never use).

---

## Step 1: Find Today's Daily Note

Compute today's date. Path pattern: `daily/YYYY/MM-MonthName/YYYY-MM-DD-DayName.md`
Use `date` command to get components, then verify with Glob if needed.

---

## Step 2: Discover Projects

### 2a. Parse Work Pipeline

Read `Work Pipeline.md`. Extract wiki-link items from `## Ideas`, `## Early`, `## Mature`.
Skip `## Complete`. Record each project's column (Ideas / Early / Mature).

### 2b. Parse Personal Pipeline

Read `Personal Pipeline.md`. Extract wiki-link items from `## Ideas`, `## Active`, `## On Hold`.
Skip `## Done`. Handle aliased links like `[[spacev3|Space V3]]`.

### 2c. Resolve File Paths

For each wiki-link, find the file:
1. `Projects/Work/<name>.md` or `Projects/Personal/<name>.md`
2. Glob `Projects/**/<name>.md` — **exclude** `Projects/Work/Archived/`
3. `Areas/<name>.md`
4. Not found → warn and skip

---

## Step 3: Gather Project Status

For each resolved project, read the note and extract:
- **Status** from `## Status` section (first sentence, max ~40 chars)
- **Matched item counts** from the `## Related Items` section (count JIRA issues, PRs, docs, etc.)
- **Deadlines** from `## Timeline` tables, `## Next Steps` dated items, and frontmatter (`deadline`/`due`/`target_date`)

Also check linked JIRA issues for target end dates (Early/Mature only):
```bash
jira issue view <KEY> --raw 2>/dev/null | python3 .claude/skills/daily-sync-all/scripts/jira_deadlines.py
```
Skip gracefully if `jira` CLI unavailable.

---

## Step 4: Write Active Projects

**Call ReplaceSection now:**
```
ReplaceSection(file_path="<daily note path>", section="active-projects", content="...")
```

Group projects by pipeline and column:

```markdown
### Active Projects

> [!info] Auto-updated by daily-summarizer on YYYY-MM-DD

**Work — Ideas**
- [[RH Cloud Region]] — no synced items

**Work — Early**
- [[Sharded ETCD Support]] — 1 PR (draft), status: design review complete
- [[Nested Virtualization Support]] — 2 PRs, status: validated on branch

**Work — Mature**
- [[ROSA Boundary]] — SSO integration phase, 1 JIRA + 2 docs
- [[HCMSTRAT-15 Agentic Coding Readiness]] — 7 JIRA, 21 PRs, 8 docs

**Personal — Active**
- [[homelab]] — no synced items
```

Each line: `[[Project Name]]` + item counts + brief status.

---

## Step 5: Write Upcoming Deadlines

**Call ReplaceSection now:**
```
ReplaceSection(file_path="<daily note path>", section="upcoming-deadlines", content="...")
```

Only include deadlines that are overdue, this week, or within next 14 days.

```markdown
### Upcoming Deadlines

> [!info] Auto-updated by daily-summarizer on YYYY-MM-DD

**Overdue**
- ⚠️ [[ROSA Boundary]] — SSO ticket submission (was due May 5) — source: project note

**This Week (May 5–11)**
- [[Sharded ETCD Support]] — sharding PR merge (May 9) — source: project note

**Next 14 Days**
- [[Fleetshift]] — architecture review (May 14) — source: project note
```

**Rules:**
- Group: Overdue (⚠️ prefix) → This Week → Next 14 Days
- Each line: `[[Project Name]]` + milestone + date + source
- Wiki-link JIRA keys in deadline lines: `[[jira/KEY|KEY]]`
- Omit groups with zero items
- If no deadlines at all, omit the entire section

---

## Step 6: Report

Output a brief summary: projects processed, item counts, deadlines surfaced, confirmation that both sections were written.
