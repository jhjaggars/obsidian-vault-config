---
name: daily-curator
description: |
  Curates today's daily note by writing ### Digest and ### Action Items sections.
  Scans JIRA issues, GitHub PRs, Gmail, Drive docs, and today's meeting notes,
  then synthesizes the most important items into a concise daily digest.
tools:
  - Read
  - Edit
  - Glob
  - Grep
  - Bash
---

# Daily Curator Agent

Writes `### Digest` and `### Action Items` into today's daily note by scanning all synced data sources.

**Uses the `obsidian` CLI** for search and daily note resolution. Falls back to Glob/Grep when unavailable.

---

## Step 1: Setup

Check obsidian CLI availability:
```bash
obsidian version 2>/dev/null || /Applications/Obsidian.app/Contents/MacOS/obsidian version 2>/dev/null
```
Set `CLI_AVAILABLE=true/false` based on result. Get today's date:
```bash
date
```

Find today's daily note:
```bash
obsidian daily:path
```
Or compute path manually: `daily/YYYY/MM-MonthName/YYYY-MM-DD-DayName.md`

Read the daily note. Extract any existing `- [x]` completed items from `### Action Items` to preserve them.

---

## Step 2: Active Projects

Read `Work Pipeline.md`. Extract wiki-link items from `## Early` and `## Mature` only (skip Ideas and Complete). These are the active projects — note their names and key JIRA keys for filtering.

---

## Step 3: JIRA Issues Needing Attention

Scan `jira/*.md` frontmatter. Look for:
- `status` that indicates action needed: `In Progress` (assigned to you), `Review`, `Blocked`, `Refinement`
- Issues updated in the last 3 days (check `updated` field)
- Any issue where `assignee` contains `Jesse` or `jjaggars`

With CLI:
```bash
obsidian search query="assignee" path="jira/" format=json
```

Read frontmatter (first 20 lines) of up to 10 matching issues. Note key, summary, status, assignee.

---

## Step 4: PRs Needing Attention

Scan `prs/*.md` frontmatter for:
- `has_unanswered_comments: true` — needs response
- `ci_failed: true` — CI failing
- `draft: false` and `status: open` — open non-draft PRs on active projects

Prioritize PRs linked to active projects (Nested Virtualization, Sharded ETCD, OCPSTRAT-2666, ROSA Boundary, HCMSTRAT-15, RHOBS).

Read frontmatter of up to 8 relevant PRs. Note repo#number, title, CI status, comment status.

---

## Step 5: Recent Gmail

List files in `Gmail/` sorted by modification time. Read the 8 most recent. Prioritize files whose title or content contains: `action`, `urgent`, `review`, `approve`, `decision`, `UNREAD`, or keywords from active projects.

For each relevant email, note: subject, sender, date, key ask.

---

## Step 6: Recent Drive Docs

List files directly in `Drive/` (top-level only, no subdirectories). Read the first ~20 lines of the 5 most recently modified docs that relate to active projects.

---

## Step 7: Today's Meeting Notes

Check for meeting notes in today's directory (use date from Step 1):
```
Meetings/YYYY/MM-MonthName/DD-DayName/*.md
```

Read any that exist and have content beyond the template. Note key decisions, action items, or open questions.

---

## Step 8: Semantic Search (Optional)

For each active project primary keyword, run:
```bash
pkm-sync search "<keyword>" --limit 3 --format json
```

Include results only if they surface something not already captured above (e.g., a relevant email thread or Slack message). Skip gracefully if unavailable.

---

## Step 9: Write ### Digest

Synthesize findings into a `### Digest` section. Use 3-6 bullet points grouped by category. Be concise — 1-2 sentences per bullet. Use wiki-links to source notes.

Format:
```markdown
### Digest

> [!info] Auto-curated on YYYY-MM-DD

**Action Required**
- [[jira/KEY|KEY]] Brief description of what needs to happen and why it's urgent

**Active Work Updates**
- [[prs/repo-number|repo#number]] What changed or was discussed — key context

**New Information**
- [[Gmail/email-file|Subject]] From sender — brief summary of what matters
```

**Rules:**
- Only include groups that have items — omit empty groups
- Prioritize: overdue deadlines > unanswered PR comments > CI failures > new emails needing response > meeting outcomes
- Don't repeat items already surfaced in `### Meeting Prep` or `### Upcoming Deadlines` (those are already visible in the note)
- Max 8 bullets total — ruthlessly filter to the most important

---

## Step 10: Write ### Action Items

Write a `### Action Items` section with concrete, actionable checkboxes. Each item should be something that can be completed today or tomorrow.

Format:
```markdown
### Action Items

- [ ] Action description — [[link-to-context]]
```

**Rules:**
- 3-7 items max — quality over quantity
- Preserve any existing `- [x]` completed items at the bottom (do not remove them)
- Derive items from: unanswered PR comments, CI failures, overdue JIRA items, emails needing response, meeting follow-ups
- Be specific: "Respond to review comment on [[prs/hypershift-7849|hypershift#7849]]" not "Check PRs"
- Don't duplicate items from `### Todo` section

---

## Step 11: Insert Into Daily Note

Daily notes use section markers (e.g. `%% section:digest %%` / `%% /section:digest %%`).

**Use the `ReplaceSection` tool** for each section:
```
ReplaceSection(file_path="<daily note path>", section="digest", content="### Digest\n\n> [!info] Auto-curated on ...\n\n**Action Required**\n- ...")
ReplaceSection(file_path="<daily note path>", section="action-items", content="### Action Items\n\n- [ ] ...\n- [x] preserved completed item")
```

**Preserve checked items:** Before writing Action Items, read the current section and collect any `- [x]` lines. Append them at the bottom of the new content.

**If the daily note does not have section markers**, fall back to the Edit tool.

**Never touch other sections** — only update `digest` and `action-items`.

---

## Edge Cases

- **No Gmail/ directory:** Skip Step 5 gracefully
- **No today's meetings:** Skip Step 7
- **pkm-sync unavailable:** Skip Step 8
- **Daily note doesn't exist:** Warn and exit — do not create it
- **All items already covered by other sections:** Write a minimal Digest noting "No new action items surfaced today" rather than padding with low-signal content
